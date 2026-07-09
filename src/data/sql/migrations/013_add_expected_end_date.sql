-- 013_add_expected_end_date.sql
-- Add an "expected end date" (planned end) to both cells and channel_history,
-- and thread it through the insert/update procs.
--
-- One migration for the whole feature: editing 005/007/009 would not add the
-- column to already-created tables (their CREATE guards skip when the object
-- exists), and the playbook is append-only. CREATE OR ALTER on the existing
-- procs preserves their EXECUTE grants from 010, so no re-grant is needed.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[cells]', N'U') IS NULL
    THROW 50000, N'Run 005 first (creates the cells table).', 1;

IF OBJECT_ID(N'[icm].[channel_history]', N'U') IS NULL
    THROW 50000, N'Run 006 first (creates the channel_history table).', 1;

-- Columns (idempotent add).
IF COL_LENGTH(N'[icm].[cells]', N'expected_end_date') IS NULL
    ALTER TABLE [icm].[cells] ADD [expected_end_date] DATE NULL;

IF COL_LENGTH(N'[icm].[channel_history]', N'expected_end_date') IS NULL
    ALTER TABLE [icm].[channel_history] ADD [expected_end_date] DATE NULL;

-- Cells: insert / update now carry expected_end_date.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_insert]
    @channel           NVARCHAR(32),
    @status            NVARCHAR(32)  = NULL,
    @project_id        NVARCHAR(128) = NULL,
    @current_owner     NVARCHAR(256) = NULL,
    @assembled_by      NVARCHAR(256) = NULL,
    @start_date        DATE          = NULL,
    @start_hour        TINYINT       = NULL,
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
        ([channel], [status], [project_id], [current_owner], [assembled_by],
         [start_date], [start_hour], [expected_end_date], [cathode], [anode],
         [data_filename], [added_water_b], [comments], [separator])
    VALUES
        (@channel, @status, @project_id, @current_owner, @assembled_by,
         @start_date, @start_hour, @expected_end_date, @cathode, @anode,
         @data_filename, @added_water_b, @comments, @separator);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_update]
    @channel           NVARCHAR(32),
    @status            NVARCHAR(32)  = NULL,
    @project_id        NVARCHAR(128) = NULL,
    @current_owner     NVARCHAR(256) = NULL,
    @assembled_by      NVARCHAR(256) = NULL,
    @start_date        DATE          = NULL,
    @start_hour        TINYINT       = NULL,
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
           [current_owner]     = @current_owner,
           [assembled_by]      = @assembled_by,
           [start_date]        = @start_date,
           [start_hour]        = @start_hour,
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

-- Channel history: insert / update now carry expected_end_date.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_history_insert]
    @channel                NVARCHAR(32),
    @project_id             NVARCHAR(128) = NULL,
    @current_owner          NVARCHAR(256) = NULL,
    @assembled_by           NVARCHAR(256) = NULL,
    @status                 NVARCHAR(32)  = NULL,
    @start_date             DATE          = NULL,
    @start_hour             TINYINT       = NULL,
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
        ([channel], [project_id], [current_owner], [assembled_by], [status],
         [start_date], [start_hour], [end_date], [expected_end_date], [cathode],
         [anode], [data_filename], [original_data_filename], [added_water_b],
         [comments], [separator])
    VALUES
        (@channel, @project_id, @current_owner, @assembled_by, @status,
         @start_date, @start_hour, @end_date, @expected_end_date, @cathode,
         @anode, @data_filename, @original_data_filename, @added_water_b,
         @comments, @separator);

    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_history_update]
    @id                     INT,
    @channel                NVARCHAR(32),
    @project_id             NVARCHAR(128) = NULL,
    @current_owner          NVARCHAR(256) = NULL,
    @assembled_by           NVARCHAR(256) = NULL,
    @status                 NVARCHAR(32)  = NULL,
    @start_date             DATE          = NULL,
    @start_hour             TINYINT       = NULL,
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
           [current_owner]          = @current_owner,
           [assembled_by]           = @assembled_by,
           [status]                 = @status,
           [start_date]             = @start_date,
           [start_hour]             = @start_hour,
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
               WHERE filename = N'013_add_expected_end_date.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'013_add_expected_end_date.sql');
GO
