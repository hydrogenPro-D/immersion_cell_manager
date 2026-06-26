-- 002_create_role_ic_manager_role.sql
-- Database role the app connects through. Granted full DML on the [icm] schema.
-- A schema-level GRANT applies to every object in [icm], including the tables
-- created later in 004-006, so this can run before they exist.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    CREATE ROLE [ic_manager_role];

-- GRANT is idempotent -- safe to re-run.
GRANT SELECT ON SCHEMA::[icm] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'002_create_role_ic_manager_role.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'002_create_role_ic_manager_role.sql');
GO
