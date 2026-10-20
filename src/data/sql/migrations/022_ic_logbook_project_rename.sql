-- 022_ic_logbook_project_rename.sql
-- IC Logbook projects can be renamed: the project row and every experiment's
-- category change together in one transaction. "Summary" is reserved (it is the
-- logbook's overview tab), so neither create nor rename accepts it.
--
-- Self-contained and safe to re-run.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'020_create_ic_logbook_projects.sql')
    THROW 50000, N'Run 020 first (creates the IC logbook projects).', 1;

-- Rename a project and move its experiments to the new name.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_project_rename]
    @old_name NVARCHAR(64), @new_name NVARCHAR(64)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    SET @new_name = LTRIM(RTRIM(@new_name));
    IF @new_name IS NULL OR @new_name = N''''
        THROW 50000, N''Project name is required.'', 1;
    IF @new_name = N''Summary''
        THROW 50000, N''"Summary" is reserved for the overview tab.'', 1;
    IF NOT EXISTS (SELECT 1 FROM [icm].[ic_logbook_project] WHERE [name] = @old_name)
        THROW 50000, N''Project not found.'', 1;
    -- Another project with that name (a case-only rename of itself is fine).
    IF EXISTS (SELECT 1 FROM [icm].[ic_logbook_project]
                WHERE [name] = @new_name AND [name] <> @old_name)
       OR EXISTS (SELECT 1 FROM [icm].[ic_logbook]  -- would merge two projects'' rows
                   WHERE [category] = @new_name AND [category] <> @old_name)
        THROW 50000, N''A project with this name already exists.'', 1;

    BEGIN TRAN;
    UPDATE [icm].[ic_logbook_project] SET [name] = @new_name WHERE [name] = @old_name;
    UPDATE [icm].[ic_logbook] SET [category] = @new_name, [updated_at] = SYSUTCDATETIME()
     WHERE [category] = @old_name;
    COMMIT;
END
');

-- Create: same as 020, plus the reserved-name check.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_project_create]
    @name NVARCHAR(64), @columns NVARCHAR(MAX), @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    SET @name = LTRIM(RTRIM(@name));
    IF @name IS NULL OR @name = N''''
        THROW 50000, N''Project name is required.'', 1;
    IF @name = N''Summary''
        THROW 50000, N''"Summary" is reserved for the overview tab.'', 1;
    IF EXISTS (SELECT 1 FROM [icm].[ic_logbook_project] WHERE [name] = @name)
        THROW 50000, N''A project with this name already exists.'', 1;
    IF ISJSON(@columns) <> 1
        THROW 50000, N''Columns must be a JSON array.'', 1;

    DECLARE @cols TABLE ([field_key] NVARCHAR(64), [label] NVARCHAR(128),
                         [data_type] NVARCHAR(16), [position] INT);
    INSERT INTO @cols
    SELECT j.[field_key], LTRIM(RTRIM(j.[label])), j.[data_type],
           CAST(k.[key] AS INT) + 1
      FROM OPENJSON(@columns) k
     CROSS APPLY OPENJSON(k.[value]) WITH (
            [field_key] NVARCHAR(64) N''$.field_key'',
            [label] NVARCHAR(128) N''$.label'',
            [data_type] NVARCHAR(16) N''$.data_type'') j;
    IF NOT EXISTS (SELECT 1 FROM @cols WHERE [field_key] = N''ic_id'')
       OR NOT EXISTS (SELECT 1 FROM @cols WHERE [field_key] = N''test_length_h'')
        THROW 50000, N''IC_ID and Test length are required columns.'', 1;

    BEGIN TRAN;
    INSERT INTO [icm].[ic_logbook_project] ([name], [sort_order])
    SELECT @name, ISNULL(MAX([sort_order]), 0) + 1 FROM [icm].[ic_logbook_project];
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
    INSERT INTO [icm].[ic_logbook_project_column]
        ([project_id], [field_key], [label], [data_type], [position])
    SELECT @id, [field_key], [label], [data_type], [position] FROM @cols;
    COMMIT;
END
');

-- CREATE OR ALTER keeps create's existing grant; only the new proc needs one.
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_project_rename] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'022_ic_logbook_project_rename.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'022_ic_logbook_project_rename.sql');
GO
