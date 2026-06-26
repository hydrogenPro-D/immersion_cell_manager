-- 009_create_history_procedures.sql
-- Insert / update stored procedures for [icm].[channel_history] (episode log).
--
-- No delete proc: the app never deletes episodes today. Project rename/delete
-- flows into history automatically via the FK (ON UPDATE CASCADE / SET NULL),
-- so it needs no dedicated proc either. The app finds the episode id with a
-- SELECT (it has read access), then calls insert or update.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

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
         [start_date], [start_hour], [end_date], [cathode], [anode],
         [data_filename], [original_data_filename], [added_water_b],
         [comments], [separator])
    VALUES
        (@channel, @project_id, @current_owner, @assembled_by, @status,
         @start_date, @start_hour, @end_date, @cathode, @anode,
         @data_filename, @original_data_filename, @added_water_b,
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
               WHERE filename = N'009_create_history_procedures.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'009_create_history_procedures.sql');
GO
