-- 001_create_schema_and_ledger.sql
-- Creates the [icm] schema and the migration ledger. RUN THIS FIRST.
--
-- Single batch (one GO only, at the very end) so a failed guard aborts the
-- whole file instead of letting later statements run anyway.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database (dataloggingDev / dataloggingTest).', 1;

-- CREATE SCHEMA must be the only statement in its batch, so run it via EXEC
-- to avoid forcing a batch break.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'icm')
    EXEC (N'CREATE SCHEMA [icm]');

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    CREATE TABLE [icm].[schema_migrations] (
        [id]             INT IDENTITY PRIMARY KEY,
        [filename]       NVARCHAR(260) NOT NULL UNIQUE,
        [applied_at_utc] DATETIME2     NOT NULL
                         CONSTRAINT [DF_schema_migrations_at] DEFAULT SYSUTCDATETIME(),
        [applied_by]     NVARCHAR(256) NOT NULL
                         CONSTRAINT [DF_schema_migrations_by] DEFAULT SUSER_SNAME()
    );

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'001_create_schema_and_ledger.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'001_create_schema_and_ledger.sql');
GO
