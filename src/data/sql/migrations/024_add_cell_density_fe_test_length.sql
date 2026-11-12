-- 024_add_cell_density_fe_test_length.sql
-- Each cell (and its history episode) gets its own density, Fe and planned test
-- length. The project's density/Fe stay as the default the app fills in, so old
-- and new electrolyte can run side by side within one project. The app computes
-- the expected end date from start + test length.
--
-- Backfill: cells take their project's current values; each cell's live
-- episode takes its cell's values. Older episodes stay empty (unknown).
--
-- Self-contained and safe to re-run. CREATE OR ALTER keeps the procs' grants.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'015_add_project_density_fe_ppm.sql')
    THROW 50000, N'Run 015 first (adds density / fe_ppm to projects).', 1;

-- ---------------------------------------------------------------- Columns

IF COL_LENGTH(N'[icm].[cells]', N'density') IS NULL
    ALTER TABLE [icm].[cells] ADD [density] NVARCHAR(64) NULL;
IF COL_LENGTH(N'[icm].[cells]', N'fe_ppm') IS NULL
    ALTER TABLE [icm].[cells] ADD [fe_ppm] NVARCHAR(64) NULL;
IF COL_LENGTH(N'[icm].[cells]', N'test_length_h') IS NULL
    ALTER TABLE [icm].[cells] ADD [test_length_h] FLOAT NULL;

IF COL_LENGTH(N'[icm].[channel_history]', N'density') IS NULL
    ALTER TABLE [icm].[channel_history] ADD [density] NVARCHAR(64) NULL;
IF COL_LENGTH(N'[icm].[channel_history]', N'fe_ppm') IS NULL
    ALTER TABLE [icm].[channel_history] ADD [fe_ppm] NVARCHAR(64) NULL;
IF COL_LENGTH(N'[icm].[channel_history]', N'test_length_h') IS NULL
    ALTER TABLE [icm].[channel_history] ADD [test_length_h] FLOAT NULL;

-- ---------------------------------------------------------------- Backfill
-- Dynamic SQL: the new columns don't exist yet when this batch is compiled.

EXEC (N'
UPDATE c
   SET c.[density] = p.[density], c.[fe_ppm] = p.[fe_ppm]
  FROM [icm].[cells] c
  JOIN [icm].[projects] p ON p.[project_id] = c.[project_id]
 WHERE c.[density] IS NULL AND c.[fe_ppm] IS NULL;

UPDATE h
   SET h.[density] = c.[density], h.[fe_ppm] = c.[fe_ppm]
  FROM [icm].[channel_history] h
  JOIN [icm].[cells] c ON c.[channel] = h.[channel]
                      AND c.[data_filename] = h.[data_filename]
 WHERE h.[density] IS NULL AND h.[fe_ppm] IS NULL;
');

-- ---------------------------------------------------------------- Procs

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_insert]
    @channel           NVARCHAR(32),
    @status            NVARCHAR(32)  = NULL,
    @project_id        NVARCHAR(128) = NULL,
    @density           NVARCHAR(64)  = NULL,
    @fe_ppm            NVARCHAR(64)  = NULL,
    @current_owner     NVARCHAR(256) = NULL,
    @assembled_by      NVARCHAR(256) = NULL,
    @start_date        DATE          = NULL,
    @start_hour        TINYINT       = NULL,
    @test_length_h     FLOAT         = NULL,
    @expected_end_date DATE          = NULL,
    @cathode           NVARCHAR(256) = NULL,
    @anode             NVARCHAR(256) = NULL,
    @data_filename     NVARCHAR(256) = NULL,
    @added_water_b     NVARCHAR(64)  = NULL,
    @comments          NVARCHAR(MAX) = NULL,
    @separator         NVARCHAR(128) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[cells]
        ([channel], [status], [project_id], [density], [fe_ppm], [current_owner],
         [assembled_by], [start_date], [start_hour], [test_length_h],
         [expected_end_date], [cathode], [anode], [data_filename], [added_water_b],
         [comments], [separator])
    VALUES
        (@channel, @status, @project_id, @density, @fe_ppm, @current_owner,
         @assembled_by, @start_date, @start_hour, @test_length_h,
         @expected_end_date, @cathode, @anode, @data_filename, @added_water_b,
         @comments, @separator);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_update]
    @channel           NVARCHAR(32),
    @status            NVARCHAR(32)  = NULL,
    @project_id        NVARCHAR(128) = NULL,
    @density           NVARCHAR(64)  = NULL,
    @fe_ppm            NVARCHAR(64)  = NULL,
    @current_owner     NVARCHAR(256) = NULL,
    @assembled_by      NVARCHAR(256) = NULL,
    @start_date        DATE          = NULL,
    @start_hour        TINYINT       = NULL,
    @test_length_h     FLOAT         = NULL,
    @expected_end_date DATE          = NULL,
    @cathode           NVARCHAR(256) = NULL,
    @anode             NVARCHAR(256) = NULL,
    @data_filename     NVARCHAR(256) = NULL,
    @added_water_b     NVARCHAR(64)  = NULL,
    @comments          NVARCHAR(MAX) = NULL,
    @separator         NVARCHAR(128) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[cells]
       SET [status]            = @status,
           [project_id]        = @project_id,
           [density]           = @density,
           [fe_ppm]            = @fe_ppm,
           [current_owner]     = @current_owner,
           [assembled_by]      = @assembled_by,
           [start_date]        = @start_date,
           [start_hour]        = @start_hour,
           [test_length_h]     = @test_length_h,
           [expected_end_date] = @expected_end_date,
           [cathode]           = @cathode,
           [anode]             = @anode,
           [data_filename]     = @data_filename,
           [added_water_b]     = @added_water_b,
           [comments]          = @comments,
           [separator]         = @separator
     WHERE [channel] = @channel;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Cell not found for the given channel.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_history_insert]
    @channel                NVARCHAR(32),
    @project_id             NVARCHAR(128) = NULL,
    @density                NVARCHAR(64)  = NULL,
    @fe_ppm                 NVARCHAR(64)  = NULL,
    @current_owner          NVARCHAR(256) = NULL,
    @assembled_by           NVARCHAR(256) = NULL,
    @status                 NVARCHAR(32)  = NULL,
    @start_date             DATE          = NULL,
    @start_hour             TINYINT       = NULL,
    @test_length_h          FLOAT         = NULL,
    @end_date               DATE          = NULL,
    @expected_end_date      DATE          = NULL,
    @cathode                NVARCHAR(256) = NULL,
    @anode                  NVARCHAR(256) = NULL,
    @data_filename          NVARCHAR(256) = NULL,
    @original_data_filename NVARCHAR(256) = NULL,
    @added_water_b          NVARCHAR(64)  = NULL,
    @comments               NVARCHAR(MAX) = NULL,
    @separator              NVARCHAR(128) = NULL,
    @id                     INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[channel_history]
        ([channel], [project_id], [density], [fe_ppm], [current_owner],
         [assembled_by], [status], [start_date], [start_hour], [test_length_h],
         [end_date], [expected_end_date], [cathode], [anode], [data_filename],
         [original_data_filename], [added_water_b], [comments], [separator])
    VALUES
        (@channel, @project_id, @density, @fe_ppm, @current_owner,
         @assembled_by, @status, @start_date, @start_hour, @test_length_h,
         @end_date, @expected_end_date, @cathode, @anode, @data_filename,
         @original_data_filename, @added_water_b, @comments, @separator);

    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_history_update]
    @id                     INT,
    @channel                NVARCHAR(32),
    @project_id             NVARCHAR(128) = NULL,
    @density                NVARCHAR(64)  = NULL,
    @fe_ppm                 NVARCHAR(64)  = NULL,
    @current_owner          NVARCHAR(256) = NULL,
    @assembled_by           NVARCHAR(256) = NULL,
    @status                 NVARCHAR(32)  = NULL,
    @start_date             DATE          = NULL,
    @start_hour             TINYINT       = NULL,
    @test_length_h          FLOAT         = NULL,
    @end_date               DATE          = NULL,
    @expected_end_date      DATE          = NULL,
    @cathode                NVARCHAR(256) = NULL,
    @anode                  NVARCHAR(256) = NULL,
    @data_filename          NVARCHAR(256) = NULL,
    @original_data_filename NVARCHAR(256) = NULL,
    @added_water_b          NVARCHAR(64)  = NULL,
    @comments               NVARCHAR(MAX) = NULL,
    @separator              NVARCHAR(128) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[channel_history]
       SET [channel]                = @channel,
           [project_id]             = @project_id,
           [density]                = @density,
           [fe_ppm]                 = @fe_ppm,
           [current_owner]          = @current_owner,
           [assembled_by]           = @assembled_by,
           [status]                 = @status,
           [start_date]             = @start_date,
           [start_hour]             = @start_hour,
           [test_length_h]          = @test_length_h,
           [end_date]               = @end_date,
           [expected_end_date]      = @expected_end_date,
           [cathode]                = @cathode,
           [anode]                  = @anode,
           [data_filename]          = @data_filename,
           [original_data_filename] = @original_data_filename,
           [added_water_b]          = @added_water_b,
           [comments]               = @comments,
           [separator]              = @separator
     WHERE [id] = @id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''History episode not found for the given id.'', 1;
END
');

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'024_add_cell_density_fe_test_length.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'024_add_cell_density_fe_test_length.sql');
GO
