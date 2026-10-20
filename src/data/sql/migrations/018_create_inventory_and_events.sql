-- 018_create_inventory_and_events.sql
-- Inventory + Event Log: two connected subsystems.
--   * Inventory: items, each with a usable and a not-usable count. A global
--     cell_count drives per-item requirements (requirement = per_cell_qty *
--     cell_count); "need to order" (requirement minus usable) is computed live in
--     the app, like the source Excel. Events deduct from usable_count.
--   * Events: a reusable event_type has a default cost recipe (event_type_cost).
--     Logging an event (event_log) snapshots the actual cost lines (event_log_cost)
--     so a deletion can be reversed. Deductions clamp at 0 (never negative); each
--     line records how much it really took (qty), so a restore gives back exactly
--     that.
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
-- per cell" multiplier used for the requirement; only usable_count counts as stock.
IF OBJECT_ID(N'[icm].[inventory_item]', N'U') IS NULL
    CREATE TABLE [icm].[inventory_item] (
        [id]             INT IDENTITY(1,1) NOT NULL
                         CONSTRAINT [PK_inventory_item] PRIMARY KEY,
        [name]           NVARCHAR(128) NOT NULL,
        [per_cell_qty]   FLOAT NOT NULL CONSTRAINT [DF_inventory_item_percell] DEFAULT (0),
        [usable_count]   INT NOT NULL CONSTRAINT [DF_inventory_item_usable] DEFAULT (0)
                         CONSTRAINT [CK_inventory_item_usable] CHECK ([usable_count] >= 0),
        [unusable_count] INT NOT NULL CONSTRAINT [DF_inventory_item_unusable] DEFAULT (0)
                         CONSTRAINT [CK_inventory_item_unusable] CHECK ([unusable_count] >= 0),
        [created_at]     DATETIME2 NOT NULL
                         CONSTRAINT [DF_inventory_item_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]     DATETIME2 NULL
    );

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
-- history; deleting the log removes these lines. qty is what was really taken
-- from usable_count (less than requested when stock ran out).
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

-- Default items from IC_Inventory.xlsx (only when the table is empty). Counts
-- start at 0; the real stock is entered in the app.
IF NOT EXISTS (SELECT 1 FROM [icm].[inventory_item])
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty])
    VALUES (N'Lids', 1), (N'Screws', 6), (N'nuts', 6), (N'Beaker', 1);

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
    @name NVARCHAR(128), @per_cell_qty FLOAT = 0,
    @usable_count INT = 0, @unusable_count INT = 0, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @usable_count < 0 SET @usable_count = 0;
    IF @unusable_count < 0 SET @unusable_count = 0;
    INSERT INTO [icm].[inventory_item]
        ([name], [per_cell_qty], [usable_count], [unusable_count])
        VALUES (@name, @per_cell_qty, @usable_count, @unusable_count);
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

-- Set exact counts (manual entry). NULL keeps that count; clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_set_counts]
    @id INT, @usable_count INT = NULL, @unusable_count INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_item]
       SET [usable_count] = CASE WHEN @usable_count IS NULL THEN [usable_count]
                                 WHEN @usable_count < 0 THEN 0 ELSE @usable_count END,
           [unusable_count] = CASE WHEN @unusable_count IS NULL THEN [unusable_count]
                                   WHEN @unusable_count < 0 THEN 0 ELSE @unusable_count END,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
END
');

-- Adjust counts by a delta (stepper +/-). Clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_adjust]
    @id INT, @usable_delta INT = 0, @unusable_delta INT = 0
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_item]
       SET [usable_count] = CASE WHEN [usable_count] + @usable_delta < 0 THEN 0
                                 ELSE [usable_count] + @usable_delta END,
           [unusable_count] = CASE WHEN [unusable_count] + @unusable_delta < 0 THEN 0
                                   ELSE [unusable_count] + @unusable_delta END,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
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

-- Append one cost line and deduct it from the item usable_count in one
-- transaction. @qty is the requested amount; takes at most what is usable and
-- stores that.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_cost_insert]
    @event_log_id INT, @item_id INT = NULL, @item_name NVARCHAR(128) = NULL,
    @qty INT, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @have INT, @taken INT = 0;
    IF @qty < 0 SET @qty = 0;
    BEGIN TRAN;
    SELECT @have = [usable_count] FROM [icm].[inventory_item] WITH (UPDLOCK, ROWLOCK)
     WHERE [id] = @item_id;
    IF @have IS NOT NULL
    BEGIN
        SET @taken = CASE WHEN @have < @qty THEN @have ELSE @qty END;
        UPDATE [icm].[inventory_item]
           SET [usable_count] = [usable_count] - @taken, [updated_at] = SYSUTCDATETIME()
         WHERE [id] = @item_id;
    END
    INSERT INTO [icm].[event_log_cost] ([event_log_id], [item_id], [item_name], [qty])
        VALUES (@event_log_id, @item_id, @item_name, @taken);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
    COMMIT;
END
');

-- Give a log entry''s taken qty back to usable_count and clear its cost lines
-- (used when editing a log''s costs, and by delete-with-restore). Lines whose
-- item was deleted have nothing to go back to.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_cost_restore]
    @event_log_id INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    UPDATE i
       SET i.[usable_count] = i.[usable_count] + t.[amount],
           i.[updated_at] = SYSUTCDATETIME()
      FROM [icm].[inventory_item] i
      JOIN (SELECT [item_id], SUM([qty]) AS [amount]
              FROM [icm].[event_log_cost]
             WHERE [event_log_id] = @event_log_id AND [qty] > 0
             GROUP BY [item_id]) t ON t.[item_id] = i.[id];
    DELETE FROM [icm].[event_log_cost] WHERE [event_log_id] = @event_log_id;
    COMMIT;
END
');

-- Delete a log entry, optionally restoring its stock first (one transaction).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_delete]
    @id INT, @restore BIT = 0
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    IF NOT EXISTS (SELECT 1 FROM [icm].[event_log] WHERE [id] = @id)
        THROW 50000, N''Event log entry not found.'', 1;
    IF @restore = 1
        EXEC [icm].[usp_event_log_cost_restore] @event_log_id = @id;
    DELETE FROM [icm].[event_log] WHERE [id] = @id;
    COMMIT;
END
');

-- ----------------------------------------------------------------- Grants

GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_config_set]       TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_insert]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_update]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_delete]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_set_counts]  TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_adjust]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_insert]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_update]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_delete]          TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_type_cost_set]        TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_insert]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_update]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_delete]           TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_cost_insert]      TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_event_log_cost_restore]     TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'018_create_inventory_and_events.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'018_create_inventory_and_events.sql');
GO
