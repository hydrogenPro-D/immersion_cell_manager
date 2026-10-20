-- 019_inventory_single_quantity.sql
-- Inventory keeps one stock count per item (users don't track usable / not
-- usable separately):
--   * inventory_item gets a quantity column holding the old usable_count values;
--     usable_count and unusable_count are dropped.
--   * usp_inventory_item_set_counts is replaced by usp_inventory_item_set_quantity;
--     usp_inventory_item_adjust takes a single @delta.
--   * The event cost procs deduct from / restore to quantity.
--
-- Self-contained and safe to re-run. Column work runs through EXEC so the batch
-- compiles before quantity exists.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'018_create_inventory_and_events.sql')
    THROW 50000, N'Run 018 first (creates the inventory tables).', 1;

-- ----------------------------------------------------------------- Columns

-- Add-copy-drop rather than sp_rename: the CHECK constraint on usable_count
-- blocks renaming the column.
IF COL_LENGTH(N'icm.inventory_item', N'quantity') IS NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] ADD [quantity] INT NOT NULL
              CONSTRAINT [DF_inventory_item_quantity] DEFAULT (0)
              CONSTRAINT [CK_inventory_item_quantity] CHECK ([quantity] >= 0);');

-- The usable count becomes the stock; the not-usable count is discarded.
IF COL_LENGTH(N'icm.inventory_item', N'usable_count') IS NOT NULL
    EXEC (N'UPDATE [icm].[inventory_item] SET [quantity] = [usable_count];');

IF OBJECT_ID(N'[icm].[CK_inventory_item_usable]') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP CONSTRAINT [CK_inventory_item_usable];');
IF OBJECT_ID(N'[icm].[DF_inventory_item_usable]') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP CONSTRAINT [DF_inventory_item_usable];');
IF COL_LENGTH(N'icm.inventory_item', N'usable_count') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP COLUMN [usable_count];');

IF OBJECT_ID(N'[icm].[CK_inventory_item_unusable]') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP CONSTRAINT [CK_inventory_item_unusable];');
IF OBJECT_ID(N'[icm].[DF_inventory_item_unusable]') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP CONSTRAINT [DF_inventory_item_unusable];');
IF COL_LENGTH(N'icm.inventory_item', N'unusable_count') IS NOT NULL
    EXEC (N'ALTER TABLE [icm].[inventory_item] DROP COLUMN [unusable_count];');

-- ----------------------------------------------------------------- Procs

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_insert]
    @name NVARCHAR(128), @per_cell_qty FLOAT = 0, @quantity INT = 0, @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @quantity < 0 SET @quantity = 0;
    INSERT INTO [icm].[inventory_item] ([name], [per_cell_qty], [quantity])
        VALUES (@name, @per_cell_qty, @quantity);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Set the exact quantity (manual entry). Clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_set_quantity]
    @id INT, @quantity INT
AS
BEGIN
    SET NOCOUNT ON;
    IF @quantity < 0 SET @quantity = 0;
    UPDATE [icm].[inventory_item]
       SET [quantity] = @quantity, [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
END
');

-- Adjust the quantity by a delta (stepper +/-). Clamps at 0.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_inventory_item_adjust]
    @id INT, @delta INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[inventory_item]
       SET [quantity] = CASE WHEN [quantity] + @delta < 0 THEN 0
                             ELSE [quantity] + @delta END,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0 THROW 50000, N''Inventory item not found.'', 1;
END
');

DROP PROCEDURE IF EXISTS [icm].[usp_inventory_item_set_counts];

-- Append one cost line and deduct it from the item quantity in one transaction.
-- @qty is the requested amount; takes at most what is in stock and stores that.
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
    SELECT @have = [quantity] FROM [icm].[inventory_item] WITH (UPDLOCK, ROWLOCK)
     WHERE [id] = @item_id;
    IF @have IS NOT NULL
    BEGIN
        SET @taken = CASE WHEN @have < @qty THEN @have ELSE @qty END;
        UPDATE [icm].[inventory_item]
           SET [quantity] = [quantity] - @taken, [updated_at] = SYSUTCDATETIME()
         WHERE [id] = @item_id;
    END
    INSERT INTO [icm].[event_log_cost] ([event_log_id], [item_id], [item_name], [qty])
        VALUES (@event_log_id, @item_id, @item_name, @taken);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
    COMMIT;
END
');

-- Give a log entry''s taken qty back to the item quantity and clear its cost
-- lines. Lines whose item was deleted have nothing to go back to.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_event_log_cost_restore]
    @event_log_id INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    UPDATE i
       SET i.[quantity] = i.[quantity] + t.[amount],
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

-- ----------------------------------------------------------------- Grants

-- CREATE OR ALTER keeps existing grants; only the new proc needs one.
GRANT EXECUTE ON OBJECT::[icm].[usp_inventory_item_set_quantity] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'019_inventory_single_quantity.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'019_inventory_single_quantity.sql');
GO
