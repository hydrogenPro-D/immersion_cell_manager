-- 008_create_project_procedures.sql
-- Insert / update / rename / delete stored procedures for [icm].[projects].
-- Rename and delete rely on the FKs from cells/channel_history:
--   rename -> ON UPDATE CASCADE flows the new name to all referencing rows;
--   delete -> ON DELETE SET NULL clears the reference on all referencing rows.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_insert]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[projects] ([project_id], [color], [description])
    VALUES (@project_id, @color, @description);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_update]
    @project_id  NVARCHAR(128),
    @color       NVARCHAR(32)   = NULL,
    @description NVARCHAR(1000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- A NULL argument means "leave that column unchanged".
    UPDATE [icm].[projects]
       SET [color]       = COALESCE(@color, [color]),
           [description] = COALESCE(@description, [description])
     WHERE [project_id] = @project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_rename]
    @old_project_id NVARCHAR(128),
    @new_project_id NVARCHAR(128),
    @color          NVARCHAR(32) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- Updating the PK cascades to cells/channel_history via ON UPDATE CASCADE.
    UPDATE [icm].[projects]
       SET [project_id] = @new_project_id,
           [color]      = COALESCE(@color, [color])
     WHERE [project_id] = @old_project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_project_delete]
    @project_id NVARCHAR(128)
AS
BEGIN
    SET NOCOUNT ON;
    -- Deleting clears the reference on cells/channel_history via ON DELETE SET NULL.
    DELETE FROM [icm].[projects] WHERE [project_id] = @project_id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Project not found.'', 1;
END
');

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'008_create_project_procedures.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'008_create_project_procedures.sql');
GO
