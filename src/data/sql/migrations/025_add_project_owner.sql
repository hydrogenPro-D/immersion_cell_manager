-- 025_add_project_owner.sql
-- A project owner (free text) on projects, set in Manage projects.
--
-- Self-contained and safe to re-run. CREATE OR ALTER keeps the procs' grants.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'015_add_project_density_fe_ppm.sql')
    THROW 50000, N'Run 015 first (the project procs this file extends).', 1;

IF COL_LENGTH(N'[icm].[projects]', N'owner') IS NULL
    ALTER TABLE [icm].[projects] ADD [owner] NVARCHAR(256) NULL;

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_insert]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL,
    @density     NVARCHAR(64)   = NULL,
    @fe_ppm      NVARCHAR(64)   = NULL,
    @owner       NVARCHAR(256)  = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[projects]
        ([project_id], [color], [description], [density], [fe_ppm], [owner])
    VALUES (@project_id, @color, @description, @density, @fe_ppm, @owner);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_update]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL,
    @density     NVARCHAR(64)   = NULL,
    @fe_ppm      NVARCHAR(64)   = NULL,
    @owner       NVARCHAR(256)  = NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- A NULL argument means "leave that column unchanged"; pass an empty string
    -- to clear a value.
    UPDATE [icm].[projects]
       SET [color]       = COALESCE(@color, [color]),
           [description] = COALESCE(@description, [description]),
           [density]     = COALESCE(@density, [density]),
           [fe_ppm]      = COALESCE(@fe_ppm, [fe_ppm]),
           [owner]       = COALESCE(@owner, [owner])
     WHERE [project_id] = @project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'025_add_project_owner.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'025_add_project_owner.sql');
GO
