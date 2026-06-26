-- 010_grant_execute_to_role.sql
-- Let the app role run the write stored procedures -- granted PER PROCEDURE
-- (not schema-wide), so the role can run exactly these procs and nothing else.
--
-- Combined with the SELECT grant from 002, this gives the app read access plus
-- write access THROUGH these procedures only (no direct INSERT/UPDATE/DELETE).
-- Ownership chaining means EXECUTE on the proc is enough -- the caller needs no
-- table DML. GRANT is idempotent, so this file is safe to re-run.
--
-- NOTE: per-proc grants mean a new write proc is NOT runnable until you add its
-- GRANT line below. Keep this list in sync with files 007-009.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

-- The procs must exist before they can be granted; make the dependency explicit.
IF (SELECT COUNT(*) FROM [icm].[schema_migrations]
    WHERE filename IN (N'007_create_cell_procedures.sql',
                       N'008_create_project_procedures.sql',
                       N'009_create_history_procedures.sql')) < 3
    THROW 50000, N'Run 007-009 first (creates the procedures).', 1;

-- Cells
GRANT EXECUTE ON OBJECT::[icm].[usp_cell_insert]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_cell_update]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_cell_delete]    TO [ic_manager_role];

-- Projects
GRANT EXECUTE ON OBJECT::[icm].[usp_project_insert] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_project_update] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_project_rename] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_project_delete] TO [ic_manager_role];

-- Channel history
GRANT EXECUTE ON OBJECT::[icm].[usp_history_insert] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_history_update] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'010_grant_execute_to_role.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'010_grant_execute_to_role.sql');
GO
