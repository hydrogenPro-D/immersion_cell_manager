-- 015_add_project_density_fe_ppm.sql
-- Add electrolyte density (rho) and iron concentration (Fe, ppm) to projects.
-- They feed the auto-generated data_filename and are shown as read-only columns
-- in Cells Mapping (editable only via Manage projects). Stored as free text (any
-- int/float), inserted into the filename verbatim.
--
-- CREATE OR ALTER on the insert/update procs preserves their EXECUTE grants from
-- 010, so no re-grant is needed (append-only playbook; 010 is never edited).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[projects]', N'U') IS NULL
    THROW 50000, N'Run 004 first (creates the projects table).', 1;

-- Columns (idempotent add).
IF COL_LENGTH(N'[icm].[projects]', N'density') IS NULL
    ALTER TABLE [icm].[projects] ADD [density] NVARCHAR(64) NULL;

IF COL_LENGTH(N'[icm].[projects]', N'fe_ppm') IS NULL
    ALTER TABLE [icm].[projects] ADD [fe_ppm] NVARCHAR(64) NULL;

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_insert]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL,
    @density     NVARCHAR(64)   = NULL,
    @fe_ppm      NVARCHAR(64)   = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[projects]
        ([project_id], [color], [description], [density], [fe_ppm])
    VALUES (@project_id, @color, @description, @density, @fe_ppm);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_update]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL,
    @density     NVARCHAR(64)   = NULL,
    @fe_ppm      NVARCHAR(64)   = NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- A NULL argument means "leave that column unchanged"; pass an empty string
    -- to clear a value.
    UPDATE [icm].[projects]
       SET [color]       = COALESCE(@color, [color]),
           [description] = COALESCE(@description, [description]),
           [density]     = COALESCE(@density, [density]),
           [fe_ppm]      = COALESCE(@fe_ppm, [fe_ppm])
     WHERE [project_id] = @project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'015_add_project_density_fe_ppm.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'015_add_project_density_fe_ppm.sql');
GO
