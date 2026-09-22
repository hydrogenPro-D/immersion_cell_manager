-- 018_create_inventory_and_events.sql
-- Inventory + Event Log: two connected subsystems.
--   * Inventory: items, each with one or more named status buckets (counts). Some
--     buckets count as "usable". A global cell_count drives per-item requirements
--     (requirement = per_cell_qty * cell_count) and "need to order" (requirement
--     minus usable) is computed live in the app, exactly like the source Excel.
--     Events deduct from an item's first usable bucket.
--   * Events: a reusable event_type has a default cost recipe (event_type_cost).
--     Logging an event (event_log) snapshots the actual cost lines (event_log_cost)
--     so a deletion can be reversed. Deductions clamp at 0 (never negative).
--
-- Self-contained: creates the tables + procs and grants EXECUTE here.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

-- ----------------------------------------------------------------- Tables

-- Global config: a single row holding the number of cells the requirements
-- target (the Excel used 70).
IF OBJECT_ID(N'[icm].[inventory_config]', N'U') IS NULL
    CREATE TABLE [icm].[inventory_config] (
        [id]         INT NOT NULL CONSTRAINT [PK_inventory_config] PRIMARY KEY
                     CONSTRAINT [CK_inventory_config_single] CHECK ([id] = 1),
        [cell_count] INT NOT NULL CONSTRAINT [DF_inventory_config_cells] DEFAULT (70)
    );

-- One row per inventory item (Lids, Screws, ...). per_cell_qty is the "how many
-- per cell" multiplier used for the requirement.
IF OBJECT_ID(N'[icm].[inventory_item]', N'U') IS NULL
    CREATE TABLE [icm].[inventory_item] (
        [id]           INT IDENTITY(1,1) NOT NULL
                       CONSTRAINT [PK_inventory_item] PRIMARY KEY,
        [name]         NVARCHAR(128) NOT NULL,
        [per_cell_qty] FLOAT NOT NULL CONSTRAINT [DF_inventory_item_percell] DEFAULT (0),
        [created_at]   DATETIME2 NOT NULL
                       CONSTRAINT [DF_inventory_item_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]   DATETIME2 NULL
    );

-- Status buckets belonging to an item. is_usable feeds the usable/order math and
-- picks the deduction target (events use the first usable bucket).
IF OBJECT_ID(N'[icm].[inventory_status]', N'U') IS NULL
    CREATE TABLE [icm].[inventory_status] (
        [id]         INT IDENTITY(1,1) NOT NULL
                     CONSTRAINT [PK_inventory_status] PRIMARY KEY,
        [item_id]    INT NOT NULL,
        [name]       NVARCHAR(128) NOT NULL,
        [count]      INT NOT NULL CONSTRAINT [DF_inventory_status_count] DEFAULT (0)
                     CONSTRAINT [CK_inventory_status_count] CHECK ([count] >= 0),
        [is_usable]  BIT NOT NULL CONSTRAINT [DF_inventory_status_usable] DEFAULT (1),
        [created_at] DATETIME2 NOT NULL
                     CONSTRAINT [DF_inventory_status_created] DEFAULT SYSUTCDATETIME(),
        [updated_at] DATETIME2 NULL,
        CONSTRAINT [FK_inventory_status_item] FOREIGN KEY ([item_id])
            REFERENCES [icm].[inventory_item] ([id]) ON DELETE CASCADE
    );

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_inventory_status_item'
                 AND object_id = OBJECT_ID(N'[icm].[inventory_status]'))
    CREATE INDEX [IX_inventory_status_item] ON [icm].[inventory_status] ([item_id]);

-- A reusable event definition.
IF OBJECT_ID(N'[icm].[event_type]', N'U') IS NULL
    CREATE TABLE [icm].[event_type] (
        [id]          INT IDENTITY(1,1) NOT NULL
                      CONSTRAINT [PK_event_type] PRIMARY KEY,
        [name]        NVARCHAR(128) NOT NULL,
        [description] NVARCHAR(MAX) NULL,
        [is_archived] BIT NOT NULL CONSTRAINT [DF_event_type_archived] DEFAULT (0),
        [created_at]  DATETIME2 NOT NULL
                      CONSTRAINT [DF_event_type_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]  DATETIME2 NULL
    );

-- Default cost recipe for an event type: how many of an item it consumes.
IF OBJECT_ID(N'[icm].[event_type_cost]', N'U') IS NULL
    CREATE TABLE [icm].[event_type_cost] (
        [id]            INT IDENTITY(1,1) NOT NULL
                        CONSTRAINT [PK_event_type_cost] PRIMARY KEY,
        [event_type_id] INT NOT NULL,
        [item_id]       INT NOT NULL,
        [qty]           INT NOT NULL CONSTRAINT [DF_event_type_cost_qty] DEFAULT (0),
        CONSTRAINT [UQ_event_type_cost] UNIQUE ([event_type_id], [item_id]),
        CONSTRAINT [FK_event_type_cost_type] FOREIGN KEY ([event_type_id])
            REFERENCES [icm].[event_type] ([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_event_type_cost_item] FOREIGN KEY ([item_id])
            REFERENCES [icm].[inventory_item] ([id]) ON DELETE CASCADE
    );

-- A logged occurrence of an event. event_name is snapshotted so the log survives
-- if the type is later renamed or removed (event_type_id then becomes NULL).
IF OBJECT_ID(N'[icm].[event_log]', N'U') IS NULL
    CREATE TABLE [icm].[event_log] (
        [id]                INT IDENTITY(1,1) NOT NULL
                            CONSTRAINT [PK_event_log] PRIMARY KEY,
        [event_type_id]     INT NULL,
        [event_name]        NVARCHAR(128) NOT NULL,
        [person]            NVARCHAR(128) NULL,
        [comment]           NVARCHAR(MAX) NULL,
        [event_date]        DATE NULL,
        [logged_at]         DATETIME2 NOT NULL
                            CONSTRAINT [DF_event_log_logged] DEFAULT SYSUTCDATETIME(),
        [created_at]        DATETIME2 NOT NULL
                            CONSTRAINT [DF_event_log_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]        DATETIME2 NULL,
        CONSTRAINT [FK_event_log_type] FOREIGN KEY ([event_type_id])
            REFERENCES [icm].[event_type] ([id]) ON DELETE SET NULL
    );

-- Snapshot of the cost lines a log entry consumed. item_id is a loose reference
-- (no FK) with a name snapshot, so items can be deleted without destroying
-- history; deleting the log removes these lines. Restore re-derives the bucket
-- from the item (its first usable status).
IF OBJECT_ID(N'[icm].[event_log_cost]', N'U') IS NULL
    CREATE TABLE [icm].[event_log_cost] (
        [id]           INT IDENTITY(1,1) NOT NULL
                       CONSTRAINT [PK_event_log_cost] PRIMARY KEY,
        [event_log_id] INT NOT NULL,
        [item_id]      INT NULL,
        [item_name]    NVARCHAR(128) NULL,
        [qty]          INT NOT NULL CONSTRAINT [DF_event_log_cost_qty] DEFAULT (0),
        CONSTRAINT [FK_event_log_cost_log] FOREIGN KEY ([event_log_id])
            REFERENCES [icm].[event_log] ([id]) ON DELETE CASCADE
    );

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_event_log_cost_log'
                 AND object_id = OBJECT_ID(N'[icm].[event_log_cost]'))
    CREATE INDEX [IX_event_log_cost_log] ON [icm].[event_log_cost] ([event_log_id]);

-- ----------------------------------------------------------------- Seed

IF NOT EXISTS (SELECT 1 FROM [icm].[inventory_config])
    INSERT INTO [icm].[inventory_config] ([id], [cell_count]) VALUES (1, 70);

-- Default items from IC_Inventory.xlsx (only when the table is empty). The two
-- unlabeled Excel buckets were merged into a single "In bag" status per item.
IF NOT EXISTS (SELECT 1 FROM [icm].[inventory_item])
BEGIN
    DECLARE @lids INT, @screws INT, @nuts INT, @beaker INT;

    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
        VALUES (N'Lids', 1);   SET @lids = SCOPE_IDENTITY();
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
        VALUES (N'Screws', 6); SET @screws = SCOPE_IDENTITY();
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
        VALUES (N'nuts', 6);   SET @nuts = SCOPE_IDENTITY();
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
        VALUES (N'Beaker', 1); SET @beaker = SCOPE_IDENTITY();

    INSERT INTO [icm].[inventory_status] ([item_id], [name], [count], [is_usable])
    VALUES
        (@lids,   N'New',       63,  1),
        (@screws, N'In bag',    676, 1),
        (@nuts,   N'In bag',    627, 1),
        (@beaker, N'Good ones', 66,  1),
        (@beaker, N'Damaged (unrepairable)', 13, 0);
END

-- ----------------------------------------------------------------- Procs

-- Config: set the global cell count.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_config_set]
    @cell_count INT
AS
BEGIN
    SET NOCOUNT ON;
    IF @cell_count < 0 SET @cell_count = 0;
    IF EXISTS (SELECT 1 FROM [icm].[inventory_config] WHERE [id] = 1)
        UPDATE [icm].[inventory_config] SET [cell_count] = @cell_count WHERE [id] = 1;
    ELSE
        INSERT INTO [icm].[inventory_config] ([id], [cell_count]) VALUES (1, @cell_count);
END
');

-- Item insert / update / delete.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_insert]
    @name NVARCHAR(128), @per_cell_qty FLOAT = 0, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
        VALUES (@name, @per_cell_qty);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_update]
    @id INT, @name NVARCHAR(128), @per_cell_qty FLOAT = 0
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_item]
       SET [name] = @name, [per_cell_qty] = @per_cell_qty,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[inventory_item] WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
END
');

-- Status insert / update (name + flags) / delete.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_status_insert]
    @item_id INT, @name NVARCHAR(128), @count INT = 0, @is_usable BIT = 1,
    @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @count < 0 SET @count = 0;
    INSERT INTO [icm].[inventory_status] ([item_id], [name], [count], [is_usable])
        VALUES (@item_id, @name, @count, @is_usable);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_status_update]
    @id INT, @name NVARCHAR(128), @is_usable BIT = 1
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_status]
       SET [name] = @name, [is_usable] = @is_usable, [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory status not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_status_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[inventory_status] WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory status not found.'', 1;
END
');

-- Set an exact count (manual entry). Clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_status_set_count]
    @id INT, @count INT
AS
BEGIN
    SET NOCOUNT ON;
    IF @count < 0 SET @count = 0;
    UPDATE [icm].[inventory_status]
       SET [count] = @count, [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory status not found.'', 1;
END
');

-- Adjust a count by a delta (stepper +/-, and event deduct/restore). Clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_status_adjust]
    @id INT, @delta INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_status]
       SET [count] = CASE WHEN [count] + @delta < 0 THEN 0 ELSE [count] + @delta END,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory status not found.'', 1;
END
');

-- Event type insert / update / delete.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_type_insert]
    @name NVARCHAR(128), @description NVARCHAR(MAX) = NULL, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[event_type] ([name], [description])
        VALUES (@name, @description);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_type_update]
    @id INT, @name NVARCHAR(128), @description NVARCHAR(MAX) = NULL,
    @is_archived BIT = 0
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[event_type]
       SET [name] = @name, [description] = @description, [is_archived] = @is_archived,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Event type not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_type_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[event_type] WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Event type not found.'', 1;
END
');

-- Upsert one recipe line; qty <= 0 removes it.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_type_cost_set]
    @event_type_id INT, @item_id INT, @qty INT
AS
BEGIN
    SET NOCOUNT ON;
    IF @qty <= 0
    BEGIN
        DELETE FROM [icm].[event_type_cost]
         WHERE [event_type_id] = @event_type_id AND [item_id] = @item_id;
        RETURN;
    END
    IF EXISTS (SELECT 1 FROM [icm].[event_type_cost]
               WHERE [event_type_id] = @event_type_id AND [item_id] = @item_id)
        UPDATE [icm].[event_type_cost] SET [qty] = @qty
         WHERE [event_type_id] = @event_type_id AND [item_id] = @item_id;
    ELSE
        INSERT INTO [icm].[event_type_cost] ([event_type_id], [item_id], [qty])
            VALUES (@event_type_id, @item_id, @qty);
END
');

-- Event log insert / update / delete.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_insert]
    @event_type_id INT = NULL, @event_name NVARCHAR(128), @person NVARCHAR(128) = NULL,
    @comment NVARCHAR(MAX) = NULL, @event_date DATE = NULL, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[event_log]
        ([event_type_id], [event_name], [person], [comment], [event_date])
        VALUES (@event_type_id, @event_name, @person, @comment, @event_date);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_update]
    @id INT, @person NVARCHAR(128) = NULL, @comment NVARCHAR(MAX) = NULL,
    @event_date DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[event_log]
       SET [person] = @person, [comment] = @comment, [event_date] = @event_date,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Event log entry not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[event_log] WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Event log entry not found.'', 1;
END
');

-- Append one snapshot cost line to a log entry.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_cost_insert]
    @event_log_id INT, @item_id INT = NULL, @item_name NVARCHAR(128) = NULL,
    @qty INT, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[event_log_cost] ([event_log_id], [item_id], [item_name], [qty])
        VALUES (@event_log_id, @item_id, @item_name, @qty);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Clear a log entry''s cost lines (used when editing a logged event''s costs:
-- restore, clear, re-insert, deduct).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_cost_delete_by_log]
    @event_log_id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[event_log_cost] WHERE [event_log_id] = @event_log_id;
END
');

-- ----------------------------------------------------------------- Grants

GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_config_set]       TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_insert]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_update]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_delete]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_status_insert]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_status_update]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_status_delete]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_status_set_count] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_status_adjust]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_insert]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_update]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_delete]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_cost_set]        TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_insert]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_update]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_delete]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_cost_insert]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_cost_delete_by_log] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'018_create_inventory_and_events.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'018_create_inventory_and_events.sql');
GO
