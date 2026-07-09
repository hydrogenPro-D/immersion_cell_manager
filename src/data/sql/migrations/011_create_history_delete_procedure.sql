-- 011_create_history_delete_procedure.sql
-- Delete stored procedure for [icm].[channel_history] (remove one episode).
--
-- Added so the Station Summary can delete a timeline entry from its details
-- dialog. Delete-by-id is a no-op if the row is already gone (idempotent), so a
-- repeated delete is harmless. Deleting an episode does not touch [icm].[cells]
-- (the live cell state); it only removes that one history row.
--
-- The EXECUTE grant lives HERE, not in 010: the playbook is append-only (never
-- edit an applied file), so a proc created after 010 grants itself.

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
CREATE OR ALTER PROCEDURE [icm].[usp_history_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[channel_history]
     WHERE [id] = @id;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_history_delete] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'011_create_history_delete_procedure.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'011_create_history_delete_procedure.sql');
GO
