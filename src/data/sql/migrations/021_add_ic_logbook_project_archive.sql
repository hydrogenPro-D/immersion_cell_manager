-- 021_add_ic_logbook_project_archive.sql
-- IC Logbook projects are archived, never deleted (their history must stay).
-- An archived project keeps all its experiments; the app just hides its tab and
-- stops offering it for new or moved entries.
--
-- Self-contained and safe to re-run.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'020_create_ic_logbook_projects.sql')
    THROW 50000, N'Run 020 first (creates the IC logbook projects).', 1;

IF COL_LENGTH(N'icm.ic_logbook_project', N'is_archived') IS NULL
    ALTER TABLE [icm].[ic_logbook_project]
        ADD [is_archived] BIT NOT NULL
            CONSTRAINT [DF_ic_logbook_project_archived] DEFAULT (0);

-- Archive or restore a project by name (the app keys projects by name).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_project_set_archived]
    @name NVARCHAR(64), @is_archived BIT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[ic_logbook_project] SET [is_archived] = @is_archived
     WHERE [name] = @name;
    IF @@ROWCOUNT = 0 THROW 50000, N''Project not found.'', 1;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_project_set_archived] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'021_add_ic_logbook_project_archive.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'021_add_ic_logbook_project_archive.sql');
GO
