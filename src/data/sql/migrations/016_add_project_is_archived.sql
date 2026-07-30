-- 016_add_project_is_archived.sql
-- Archive projects instead of deleting them. An archived project stays assigned
-- on every channel and station-summary episode that already uses it; it is only
-- hidden from the "assign a project" dropdowns so it can't be picked for new
-- channels. Archiving is reversible (restore) from the Manage Projects window.
--
-- New proc, so it grants EXECUTE here (append-only playbook; 010 is never edited).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[projects]', N'U') IS NULL
    THROW 50000, N'Run 004 first (creates the projects table).', 1;

-- Column (idempotent add). NOT NULL default 0 -> existing projects stay active.
IF COL_LENGTH(N'[icm].[projects]', N'is_archived') IS NULL
    ALTER TABLE [icm].[projects] ADD [is_archived] BIT NOT NULL
        CONSTRAINT [DF_projects_is_archived] DEFAULT 0;

-- Set / clear the archived flag (1 = archive, 0 = restore).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_set_archived]
    @project_id  NVARCHAR(128),
    @is_archived BIT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[projects] SET [is_archived] = @is_archived
     WHERE [project_id] = @project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_project_set_archived] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'016_add_project_is_archived.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'016_add_project_is_archived.sql');
GO
