-- 004_create_projects_table.sql
-- Project lookup table. Mirrors projects.csv (project_id = the project name).
-- Referenced by [icm].[cells] and [icm].[channel_history].

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[projects]', N'U') IS NULL
    CREATE TABLE [icm].[projects] (
        [id]          INT IDENTITY(1,1) NOT NULL
                      CONSTRAINT [PK_projects] PRIMARY KEY,
        -- project_id is the project NAME and the business key. It stays UNIQUE
        -- because the cells/history FKs reference it.
        [project_id]  NVARCHAR(128)  NOT NULL
                      CONSTRAINT [UQ_projects_project_id] UNIQUE,
        [color]       NVARCHAR(32)   NULL,   -- hex string, e.g. '#3FA3A3'
        [description] NVARCHAR(1000) NULL
    );

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'004_create_projects_table.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'004_create_projects_table.sql');
GO
