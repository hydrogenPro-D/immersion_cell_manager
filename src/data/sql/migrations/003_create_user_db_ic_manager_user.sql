-- 003_create_user_db_ic_manager_user.sql
-- Contained app user (Azure SQL), created WITH PASSWORD and added to the role.
--
-- PASSWORD WORKFLOW (per the playbook): type a real password into @pw below,
-- run the file, then CLOSE IT WITHOUT SAVING. The committed file keeps only the
-- placeholder, and the guard below throws if you forget to set one.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

DECLARE @pw NVARCHAR(128) = N'<<SET_PASSWORD_HERE_THEN_DO_NOT_SAVE>>';

IF @pw LIKE N'%<<%' OR @pw LIKE N'%>>%' OR LEN(@pw) < 8
    THROW 50000, N'Set a real password before running this file.', 1;

-- WITH PASSWORD needs a string literal, and EXEC() cannot contain function
-- calls, so escape the password into a variable first, then EXEC the variable.
-- REPLACE doubles single quotes so the password can't break out of the literal.
DECLARE @sql NVARCHAR(MAX) =
    N'CREATE USER [db_ic_manager_user] WITH PASSWORD = N'''
    + REPLACE(@pw, N'''', N'''''') + N'''';
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'db_ic_manager_user')
    EXEC (@sql);

IF NOT EXISTS (
    SELECT 1 FROM sys.database_role_members rm
    JOIN sys.database_principals r ON rm.role_principal_id   = r.principal_id
    JOIN sys.database_principals m ON rm.member_principal_id = m.principal_id
    WHERE r.name = N'ic_manager_role' AND m.name = N'db_ic_manager_user')
    ALTER ROLE [ic_manager_role] ADD MEMBER [db_ic_manager_user];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'003_create_user_db_ic_manager_user.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'003_create_user_db_ic_manager_user.sql');
GO
