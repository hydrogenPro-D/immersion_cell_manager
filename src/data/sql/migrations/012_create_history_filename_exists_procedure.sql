-- 012_create_history_filename_exists_procedure.sql
-- Read-only check: is a data_filename already used in [icm].[channel_history]?
--
-- data_filename acts as a unique key for an experiment. Before saving a cell or
-- modifying an episode, the app calls this to block duplicates. @exclude_id lets
-- the caller ignore the row being edited (so it doesn't flag its own filename).
-- Blank/NULL filenames are never duplicates (Available / In repair rows).
--
-- Returns one row: match_count (0 = free, >= 1 = already taken). Case-insensitive
-- (default collation, matching Windows filename behaviour).
--
-- The EXECUTE grant lives HERE, not in 010 (append-only playbook: 010 is applied
-- and never edited again).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[channel_history]', N'U') IS NULL
    THROW 50000, N'Run 006 first (creates the channel_history table).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_history_filename_exists]
    @data_filename NVARCHAR(256),
    @exclude_id    INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @data_filename IS NULL OR LTRIM(RTRIM(@data_filename)) = N''''
    BEGIN
        SELECT CAST(0 AS INT) AS match_count;
        RETURN;
    END
    SELECT COUNT(*) AS match_count
    FROM [icm].[channel_history]
    WHERE [data_filename] = @data_filename
      AND (@exclude_id IS NULL OR [id] <> @exclude_id);
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_history_filename_exists] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'012_create_history_filename_exists_procedure.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'012_create_history_filename_exists_procedure.sql');
GO
