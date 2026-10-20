-- 020_create_ic_logbook_projects.sql
-- IC Logbook projects become explicit, each with its own column list:
--   * ic_logbook_project: one row per project (= logbook sub-tab), in tab order.
--   * ic_logbook_project_column: the columns a project shows, in order.
--     field_key is a built-in ic_logbook column (ic_id, owner, ...) or a custom
--     key (x_...) whose values live in ic_logbook_value. data_type: text /
--     number / date.
--   * ic_logbook_value: values of custom columns, one row per experiment + key.
-- ic_logbook.category keeps naming the project (matched by name). The existing
-- projects are seeded with the columns they use today.
--
-- Self-contained and safe to re-run. Needs OPENJSON (Azure SQL has it).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'017_create_ic_logbook_tables_and_procs.sql')
    THROW 50000, N'Run 017 first (creates the IC logbook).', 1;

-- ----------------------------------------------------------------- Tables

IF OBJECT_ID(N'[icm].[ic_logbook_project]', N'U') IS NULL
    CREATE TABLE [icm].[ic_logbook_project] (
        [id]         INT IDENTITY(1,1) NOT NULL
                     CONSTRAINT [PK_ic_logbook_project] PRIMARY KEY,
        [name]       NVARCHAR(64) NOT NULL       -- = ic_logbook.category
                     CONSTRAINT [UQ_ic_logbook_project_name] UNIQUE,
        [sort_order] INT NOT NULL,
        [created_at] DATETIME2 NOT NULL
                     CONSTRAINT [DF_ic_logbook_project_created] DEFAULT SYSUTCDATETIME()
    );

IF OBJECT_ID(N'[icm].[ic_logbook_project_column]', N'U') IS NULL
    CREATE TABLE [icm].[ic_logbook_project_column] (
        [id]         INT IDENTITY(1,1) NOT NULL
                     CONSTRAINT [PK_ic_logbook_project_column] PRIMARY KEY,
        [project_id] INT NOT NULL,
        [field_key]  NVARCHAR(64) NOT NULL,
        [label]      NVARCHAR(128) NOT NULL,
        [data_type]  NVARCHAR(16) NOT NULL
                     CONSTRAINT [CK_ic_logbook_project_column_type]
                     CHECK ([data_type] IN (N'text', N'number', N'date')),
        [position]   INT NOT NULL,
        CONSTRAINT [UQ_ic_logbook_project_column] UNIQUE ([project_id], [field_key]),
        CONSTRAINT [FK_ic_logbook_project_column_project] FOREIGN KEY ([project_id])
            REFERENCES [icm].[ic_logbook_project] ([id]) ON DELETE CASCADE
    );

IF OBJECT_ID(N'[icm].[ic_logbook_value]', N'U') IS NULL
    CREATE TABLE [icm].[ic_logbook_value] (
        [id]         INT IDENTITY(1,1) NOT NULL
                     CONSTRAINT [PK_ic_logbook_value] PRIMARY KEY,
        [logbook_id] INT NOT NULL,
        [field_key]  NVARCHAR(64) NOT NULL,
        [value]      NVARCHAR(MAX) NULL,
        CONSTRAINT [UQ_ic_logbook_value] UNIQUE ([logbook_id], [field_key]),
        CONSTRAINT [FK_ic_logbook_value_logbook] FOREIGN KEY ([logbook_id])
            REFERENCES [icm].[ic_logbook] ([id]) ON DELETE CASCADE
    );

-- ----------------------------------------------------------------- Seed

-- Existing projects in the workbook's tab order, then any other category found
-- in the data (first-seen order).
IF NOT EXISTS (SELECT 1 FROM [icm].[ic_logbook_project])
BEGIN
    INSERT INTO [icm].[ic_logbook_project] ([name], [sort_order])
    SELECT v.[name], v.[ord]
      FROM (VALUES (N'Gen2-Gen2', 1), (N'Gen3-Gen3', 2), (N'Gen2-Gen3Ano', 3),
                   (N'Gen3Cat-Gen2', 4), (N'Gen4Cat-Gen2', 5), (N'Accelerated', 6),
                   (N'H2-FOAM', 7), (N'LC-H2', 8), (N'H2-Electrode', 9), (N'H2-SAF', 10),
                   (N'H2-Giga', 11), (N'MLF', 12), (N'Sulfidized', 13),
                   (N'Substrate tests', 14), (N'External | Meshes', 15),
                   (N'Production R&D', 16), (N'Long term testing', 17),
                   (N'Iron tests', 18), (N'Other', 19)) v ([name], [ord])
     WHERE EXISTS (SELECT 1 FROM [icm].[ic_logbook] l WHERE l.[category] = v.[name]);

    INSERT INTO [icm].[ic_logbook_project] ([name], [sort_order])
    SELECT l.[category], 100 + ROW_NUMBER() OVER (ORDER BY MIN(l.[id]))
      FROM [icm].[ic_logbook] l
     WHERE NULLIF(LTRIM(RTRIM(l.[category])), N'') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM [icm].[ic_logbook_project] p
                        WHERE p.[name] = l.[category])
     GROUP BY l.[category];

    -- Every project: the 11 standard columns.
    INSERT INTO [icm].[ic_logbook_project_column]
        ([project_id], [field_key], [label], [data_type], [position])
    SELECT p.[id], s.[field_key], s.[label], s.[data_type], s.[position]
      FROM [icm].[ic_logbook_project] p
     CROSS JOIN (VALUES
        (N'ic_id', N'IC_ID', N'text', 1),
        (N'owner', N'Owner', N'text', 2),
        (N'assembled_by', N'Assembled by', N'text', 3),
        (N'disassembled_by', N'Disassembled by', N'text', 4),
        (N'test_length_h', N'Test length [h]', N'number', 5),
        (N'protocol', N'Protocol', N'text', 6),
        (N'format', N'Format', N'text', 7),
        (N'experiment_finished_on', N'Experiment finished on', N'date', 8),
        (N'notes', N'Notes', N'text', 9),
        (N'archived_in', N'Archived in', N'text', 10),
        (N'plot', N'Plot', N'text', 11)) s ([field_key], [label], [data_type], [position]);

    -- Synthesis columns only where a project already has such data (Sulfidized).
    INSERT INTO [icm].[ic_logbook_project_column]
        ([project_id], [field_key], [label], [data_type], [position])
    SELECT p.[id], e.[field_key], e.[label], e.[data_type], e.[position]
      FROM [icm].[ic_logbook_project] p
     CROSS JOIN (VALUES
        (N'synthesis_recipe', N'Synthesis recipe', N'text', 12),
        (N'synthesis_time_h', N'Synthesis time (h)', N'number', 13),
        -- NCHAR(176) = degree sign; spelled out so the file's encoding can't garble it.
        (N'synthesis_temperature_c', N'Synthesis temp (' + NCHAR(176) + N'C)', N'number', 14),
        (N'coating_test_on', N'Coating test on', N'text', 15)) e ([field_key], [label], [data_type], [position])
     WHERE EXISTS (
        SELECT 1 FROM [icm].[ic_logbook] l
         WHERE l.[category] = p.[name]
           AND ((e.[field_key] = N'synthesis_recipe' AND NULLIF(LTRIM(l.[synthesis_recipe]), N'') IS NOT NULL)
             OR (e.[field_key] = N'synthesis_time_h' AND l.[synthesis_time_h] IS NOT NULL)
             OR (e.[field_key] = N'synthesis_temperature_c' AND l.[synthesis_temperature_c] IS NOT NULL)
             OR (e.[field_key] = N'coating_test_on' AND NULLIF(LTRIM(l.[coating_test_on]), N'') IS NOT NULL)));
END

-- ----------------------------------------------------------------- Procs

-- Create a project and its columns in one transaction. @columns is a JSON array
-- of {"field_key", "label", "data_type"} in display order. ic_id and
-- test_length_h are required (IC_ID identifies a row; hours feed the Summary).
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

-- Set one custom-column value of an experiment; empty or NULL removes it.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_value_set]
    @logbook_id INT, @field_key NVARCHAR(64), @value NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF NULLIF(LTRIM(RTRIM(@value)), N'''') IS NULL
    BEGIN
        DELETE FROM [icm].[ic_logbook_value]
         WHERE [logbook_id] = @logbook_id AND [field_key] = @field_key;
        RETURN;
    END
    IF EXISTS (SELECT 1 FROM [icm].[ic_logbook_value]
                WHERE [logbook_id] = @logbook_id AND [field_key] = @field_key)
        UPDATE [icm].[ic_logbook_value] SET [value] = @value
         WHERE [logbook_id] = @logbook_id AND [field_key] = @field_key;
    ELSE
        INSERT INTO [icm].[ic_logbook_value] ([logbook_id], [field_key], [value])
        VALUES (@logbook_id, @field_key, @value);
END
');

-- ----------------------------------------------------------------- Grants

GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_project_create] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_value_set]      TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'020_create_ic_logbook_projects.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'020_create_ic_logbook_projects.sql');
GO
