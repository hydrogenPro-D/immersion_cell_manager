-- 007_create_cell_procedures.sql
-- Insert / update / delete stored procedures for [icm].[cells].
-- The app writes ONLY through these procs (it has SELECT, but no direct DML).
--
-- Each proc is created via EXEC(N'CREATE OR ALTER PROCEDURE ...') so the whole
-- file stays a single batch: CREATE PROCEDURE must otherwise be the first
-- statement in its batch, which would force a batch break and defeat the guard.
-- CREATE OR ALTER makes re-running safe (idempotent).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_insert]
    @channel       NVARCHAR(32),
    @status        NVARCHAR(32)  = NULL,
    @project_id    NVARCHAR(128) = NULL,
    @current_owner NVARCHAR(256) = NULL,
    @assembled_by  NVARCHAR(256) = NULL,
    @start_date    DATE          = NULL,
    @start_hour    TINYINT       = NULL,
    @cathode       NVARCHAR(256) = NULL,
    @anode         NVARCHAR(256) = NULL,
    @data_filename NVARCHAR(256) = NULL,
    @added_water_b NVARCHAR(64)  = NULL,
    @comments      NVARCHAR(MAX) = NULL,
    @separator     NVARCHAR(128) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[cells]
        ([channel], [status], [project_id], [current_owner], [assembled_by],
         [start_date], [start_hour], [cathode], [anode], [data_filename],
         [added_water_b], [comments], [separator])
    VALUES
        (@channel, @status, @project_id, @current_owner, @assembled_by,
         @start_date, @start_hour, @cathode, @anode, @data_filename,
         @added_water_b, @comments, @separator);
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_update]
    @channel       NVARCHAR(32),
    @status        NVARCHAR(32)  = NULL,
    @project_id    NVARCHAR(128) = NULL,
    @current_owner NVARCHAR(256) = NULL,
    @assembled_by  NVARCHAR(256) = NULL,
    @start_date    DATE          = NULL,
    @start_hour    TINYINT       = NULL,
    @cathode       NVARCHAR(256) = NULL,
    @anode         NVARCHAR(256) = NULL,
    @data_filename NVARCHAR(256) = NULL,
    @added_water_b NVARCHAR(64)  = NULL,
    @comments      NVARCHAR(MAX) = NULL,
    @separator     NVARCHAR(128) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[cells]
       SET [status]        = @status,
           [project_id]    = @project_id,
           [current_owner] = @current_owner,
           [assembled_by]  = @assembled_by,
           [start_date]    = @start_date,
           [start_hour]    = @start_hour,
           [cathode]       = @cathode,
           [anode]         = @anode,
           [data_filename] = @data_filename,
           [added_water_b] = @added_water_b,
           [comments]      = @comments,
           [separator]     = @separator
     WHERE [channel] = @channel;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Cell not found for the given channel.'', 1;
END
');

EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_cell_delete]
    @channel NVARCHAR(32)
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[cells] WHERE [channel] = @channel;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Cell not found for the given channel.'', 1;
END
');

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'007_create_cell_procedures.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'007_create_cell_procedures.sql');
GO
