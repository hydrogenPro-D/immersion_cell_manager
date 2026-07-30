-- 014_create_calibration_table_and_procs.sql
-- Channel calibration: one row per calibration measurement (history). The app
-- computes the ΔV% per resistance and evaluates pass/fail against the bounds in
-- config/calibration_config.json; a human then Approves/Rejects (the "decision").
--
-- Self-contained: creates the table + its procs and grants EXECUTE here (the
-- playbook is append-only, so 010 is never edited again).
--
-- channel is NOT a FK to icm.cells (calibration history outlives a deleted cell,
-- same as channel_history).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

-- Table (measured potentials p_* are the raw readings; ΔV% is derived by the app).
IF OBJECT_ID(N'[icm].[channel_calibration]', N'U') IS NULL
    CREATE TABLE [icm].[channel_calibration] (
        [id]              INT IDENTITY(1,1) NOT NULL
                          CONSTRAINT [PK_channel_calibration] PRIMARY KEY,
        [channel]         NVARCHAR(32)  NOT NULL,
        [measured_date]   DATE          NULL,
        [ic_number]       NVARCHAR(64)  NULL,
        [measured_by]     NVARCHAR(256) NULL,
        [applied_current] FLOAT         NULL,        -- amperes (usually 0.92)
        [p_1_0]           FLOAT         NULL,        -- measured potential at 1.0 ohm
        [p_1_5]           FLOAT         NULL,        -- 1.5 ohm
        [p_2_0]           FLOAT         NULL,        -- 2.0 ohm
        [p_3_3]           FLOAT         NULL,        -- 3.3 ohm
        [p_4_0]           FLOAT         NULL,        -- 4.0 ohm
        [p_5_0]           FLOAT         NULL,        -- 5.0 ohm
        [decision]        NVARCHAR(32)  NULL,        -- 'Awaiting decision' | 'Pass' | 'Fail'
        [decided_by]      NVARCHAR(256) NULL,
        [decided_at]      DATETIME2     NULL,
        [note]            NVARCHAR(MAX) NULL,
        [created_at]      DATETIME2     NOT NULL
                          CONSTRAINT [DF_channel_calibration_created] DEFAULT SYSUTCDATETIME()
    );

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_channel_calibration_channel'
                 AND object_id = OBJECT_ID(N'[icm].[channel_calibration]'))
    CREATE INDEX [IX_channel_calibration_channel]
        ON [icm].[channel_calibration] ([channel], [measured_date], [id]);

-- Insert a measurement. Defaults the decision to 'Awaiting decision'.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_calibration_insert]
    @channel         NVARCHAR(32),
    @measured_date   DATE          = NULL,
    @ic_number       NVARCHAR(64)  = NULL,
    @measured_by     NVARCHAR(256) = NULL,
    @applied_current FLOAT         = NULL,
    @p_1_0           FLOAT         = NULL,
    @p_1_5           FLOAT         = NULL,
    @p_2_0           FLOAT         = NULL,
    @p_3_3           FLOAT         = NULL,
    @p_4_0           FLOAT         = NULL,
    @p_5_0           FLOAT         = NULL,
    @decision        NVARCHAR(32)  = N''Awaiting decision'',
    @note            NVARCHAR(MAX) = NULL,
    @id              INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[channel_calibration]
        ([channel], [measured_date], [ic_number], [measured_by], [applied_current],
         [p_1_0], [p_1_5], [p_2_0], [p_3_3], [p_4_0], [p_5_0],
         [decision], [note])
    VALUES
        (@channel, @measured_date, @ic_number, @measured_by, @applied_current,
         @p_1_0, @p_1_5, @p_2_0, @p_3_3, @p_4_0, @p_5_0,
         @decision, @note);

    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Update a measurement''s entered values. The app resets @decision to
-- ''Awaiting decision'' when the readings change (a prior verdict no longer holds).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_calibration_update]
    @id              INT,
    @channel         NVARCHAR(32),
    @measured_date   DATE          = NULL,
    @ic_number       NVARCHAR(64)  = NULL,
    @measured_by     NVARCHAR(256) = NULL,
    @applied_current FLOAT         = NULL,
    @p_1_0           FLOAT         = NULL,
    @p_1_5           FLOAT         = NULL,
    @p_2_0           FLOAT         = NULL,
    @p_3_3           FLOAT         = NULL,
    @p_4_0           FLOAT         = NULL,
    @p_5_0           FLOAT         = NULL,
    @decision        NVARCHAR(32)  = NULL,
    @note            NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[channel_calibration]
       SET [channel]         = @channel,
           [measured_date]   = @measured_date,
           [ic_number]       = @ic_number,
           [measured_by]     = @measured_by,
           [applied_current] = @applied_current,
           [p_1_0]           = @p_1_0,
           [p_1_5]           = @p_1_5,
           [p_2_0]           = @p_2_0,
           [p_3_3]           = @p_3_3,
           [p_4_0]           = @p_4_0,
           [p_5_0]           = @p_5_0,
           [decision]        = @decision,
           [note]            = @note,
           -- editing the readings invalidates any prior sign-off
           [decided_by]      = NULL,
           [decided_at]      = NULL
     WHERE [id] = @id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Calibration measurement not found for the given id.'', 1;
END
');

-- Record a human decision (Approve -> ''Pass'', Reject -> ''Fail'').
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_calibration_set_decision]
    @id         INT,
    @decision   NVARCHAR(32),
    @decided_by NVARCHAR(256) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[channel_calibration]
       SET [decision]   = @decision,
           [decided_by] = @decided_by,
           [decided_at] = SYSUTCDATETIME()
     WHERE [id] = @id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Calibration measurement not found for the given id.'', 1;
END
');

-- Delete a single measurement.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_calibration_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[channel_calibration] WHERE [id] = @id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''Calibration measurement not found for the given id.'', 1;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_calibration_insert]       TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_calibration_update]       TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_calibration_set_decision] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_calibration_delete]       TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'014_create_calibration_table_and_procs.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'014_create_calibration_table_and_procs.sql');
GO
