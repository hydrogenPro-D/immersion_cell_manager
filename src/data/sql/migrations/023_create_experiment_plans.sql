-- 023_create_experiment_plans.sql
-- Experiment planning: a plan is submitted (pending), approved (scheduled, in a
-- drag-and-drop priority order) and finally loaded into a cell (started).
-- Plans are never deleted: a deleted or started plan keeps its row, the app
-- only shows pending and scheduled ones.
--
-- Self-contained and safe to re-run.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

IF OBJECT_ID(N'[icm].[experiment_plan]', N'U') IS NULL
    CREATE TABLE [icm].[experiment_plan] (
        [id]              INT IDENTITY(1,1) NOT NULL
                          CONSTRAINT [PK_experiment_plan] PRIMARY KEY,
        [name]            NVARCHAR(256) NOT NULL,
        [test_length_h]   FLOAT NULL,
        [anode]           NVARCHAR(256) NULL,
        [cathode]         NVARCHAR(256) NULL,
        [protocol]        NVARCHAR(256) NULL,
        [project_id]      NVARCHAR(128) NULL,    -- a Cells mapping project
        [aim]             NVARCHAR(MAX) NULL,
        [urgency]         NVARCHAR(16) NOT NULL
                          CONSTRAINT [DF_experiment_plan_urgency] DEFAULT (N'Normal')
                          CONSTRAINT [CK_experiment_plan_urgency]
                          CHECK ([urgency] IN (N'Low', N'Normal', N'High', N'Urgent')),
        [channel]         NVARCHAR(32) NULL,     -- a fixed cell; NULL = any available cell
        [status]          NVARCHAR(16) NOT NULL
                          CONSTRAINT [DF_experiment_plan_status] DEFAULT (N'pending')
                          CONSTRAINT [CK_experiment_plan_status]
                          CHECK ([status] IN (N'pending', N'scheduled', N'started', N'deleted')),
        [priority]        INT NULL,              -- order in the schedule (1 = first)
        [approved_by]     NVARCHAR(128) NULL,
        [approved_at]     DATETIME2 NULL,
        [started_channel] NVARCHAR(32) NULL,     -- where it was loaded (history)
        [started_at]      DATETIME2 NULL,
        [created_at]      DATETIME2 NOT NULL
                          CONSTRAINT [DF_experiment_plan_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]      DATETIME2 NULL,
        -- Same as cells: a project rename flows through, a delete clears it.
        -- No FK on channel: a second cascade path from projects (via cells) is
        -- refused by SQL Server. The app checks the channel when loading.
        CONSTRAINT [FK_experiment_plan_project] FOREIGN KEY ([project_id])
            REFERENCES [icm].[projects] ([project_id])
            ON UPDATE CASCADE ON DELETE SET NULL
    );

-- Submit a new plan (pending).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_insert]
    @name NVARCHAR(256), @test_length_h FLOAT = NULL, @anode NVARCHAR(256) = NULL,
    @cathode NVARCHAR(256) = NULL, @protocol NVARCHAR(256) = NULL,
    @project_id NVARCHAR(128) = NULL, @aim NVARCHAR(MAX) = NULL,
    @urgency NVARCHAR(16) = N''Normal'', @id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF NULLIF(LTRIM(RTRIM(@name)), N'''') IS NULL
        THROW 50000, N''Plan name is required.'', 1;
    INSERT INTO [icm].[experiment_plan]
        ([name], [test_length_h], [anode], [cathode], [protocol], [project_id], [aim], [urgency])
    VALUES (LTRIM(RTRIM(@name)), @test_length_h, @anode, @cathode, @protocol, @project_id,
            @aim, ISNULL(@urgency, N''Normal''));
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Edit a pending or scheduled plan (all fields, including the channel).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_update]
    @id INT, @name NVARCHAR(256), @test_length_h FLOAT = NULL, @anode NVARCHAR(256) = NULL,
    @cathode NVARCHAR(256) = NULL, @protocol NVARCHAR(256) = NULL,
    @project_id NVARCHAR(128) = NULL, @aim NVARCHAR(MAX) = NULL,
    @urgency NVARCHAR(16) = N''Normal'', @channel NVARCHAR(32) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF NULLIF(LTRIM(RTRIM(@name)), N'''') IS NULL
        THROW 50000, N''Plan name is required.'', 1;
    UPDATE [icm].[experiment_plan]
       SET [name] = LTRIM(RTRIM(@name)), [test_length_h] = @test_length_h,
           [anode] = @anode, [cathode] = @cathode, [protocol] = @protocol,
           [project_id] = @project_id, [aim] = @aim,
           [urgency] = ISNULL(@urgency, N''Normal''), [channel] = @channel,
           [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id AND [status] IN (N''pending'', N''scheduled'');
    IF @@ROWCOUNT = 0
        THROW 50000, N''This plan was loaded or deleted by someone else.'', 1;
END
');

-- Approve: pending -> scheduled, last in the schedule.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_approve]
    @id INT, @approved_by NVARCHAR(128)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NULLIF(LTRIM(RTRIM(@approved_by)), N'''') IS NULL
        THROW 50000, N''The approver''''s name is required.'', 1;
    BEGIN TRAN;
    UPDATE [icm].[experiment_plan]
       SET [status] = N''scheduled'', [approved_by] = LTRIM(RTRIM(@approved_by)),
           [approved_at] = SYSUTCDATETIME(), [updated_at] = SYSUTCDATETIME(),
           [priority] = (SELECT ISNULL(MAX([priority]), 0) + 1
                           FROM [icm].[experiment_plan] WITH (UPDLOCK, HOLDLOCK)
                          WHERE [status] = N''scheduled'')
     WHERE [id] = @id AND [status] = N''pending'';
    IF @@ROWCOUNT = 0
        THROW 50000, N''This plan is no longer pending (someone else changed it).'', 1;
    COMMIT;
END
');

-- Back to pending (approval withdrawn).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_unapprove]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[experiment_plan]
       SET [status] = N''pending'', [priority] = NULL, [approved_by] = NULL,
           [approved_at] = NULL, [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id AND [status] = N''scheduled'';
    IF @@ROWCOUNT = 0
        THROW 50000, N''This plan is no longer scheduled (someone else changed it).'', 1;
END
');

-- New schedule order: @ids is a JSON array of plan ids, first = top priority.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_reorder]
    @ids NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    IF ISJSON(@ids) <> 1
        THROW 50000, N''The order must be a JSON array of ids.'', 1;
    UPDATE p
       SET [priority] = CAST(j.[key] AS INT) + 1
      FROM [icm].[experiment_plan] p
      JOIN OPENJSON(@ids) j ON p.[id] = CAST(j.[value] AS INT)
     WHERE p.[status] = N''scheduled'';
END
');

-- Delete = mark deleted (the row stays).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[experiment_plan]
       SET [status] = N''deleted'', [priority] = NULL, [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id AND [status] IN (N''pending'', N''scheduled'');
    IF @@ROWCOUNT = 0
        THROW 50000, N''This plan was already loaded or deleted.'', 1;
END
');

-- Loaded into a cell: mark started with the channel (the row stays).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_experiment_plan_start]
    @id INT, @channel NVARCHAR(32)
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[experiment_plan]
       SET [status] = N''started'', [priority] = NULL, [started_channel] = @channel,
           [started_at] = SYSUTCDATETIME(), [updated_at] = SYSUTCDATETIME()
     WHERE [id] = @id AND [status] = N''scheduled'';
    IF @@ROWCOUNT = 0
        THROW 50000, N''This plan is no longer scheduled (someone else changed it).'', 1;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_insert]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_update]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_approve]   TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_unapprove] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_reorder]   TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_delete]    TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_experiment_plan_start]     TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'023_create_experiment_plans.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'023_create_experiment_plans.sql');
GO
