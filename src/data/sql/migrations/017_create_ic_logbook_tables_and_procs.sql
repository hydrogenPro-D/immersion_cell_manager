-- 017_create_ic_logbook_tables_and_procs.sql
-- IC Logbook: historical experiments (imported from IC_Logbook.xlsx) plus the
-- manual Summary "scoreboard" snapshots. Key is an auto-increment id; ic_id is a
-- plain, NON-unique text column (ids aren't unique/consistent). category is free
-- text. The Summary dashboard is computed live, so there is no summary table.
--
-- Self-contained: creates the tables + procs and grants EXECUTE here (the
-- append-only playbook means 010 is never edited again).

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'ic_manager_role' AND type = 'R')
    THROW 50000, N'Run 002 first (creates the role).', 1;

-- Experiments (one row each; the Sulfidized synthesis_* columns stay NULL elsewhere).
IF OBJECT_ID(N'[icm].[ic_logbook]', N'U') IS NULL
    CREATE TABLE [icm].[ic_logbook] (
        [id]                      INT IDENTITY(1,1) NOT NULL
                                  CONSTRAINT [PK_ic_logbook] PRIMARY KEY,
        [category]                NVARCHAR(64)  NULL,
        [ic_id]                   NVARCHAR(256) NULL,    -- non-unique, may be blank
        [owner]                   NVARCHAR(128) NULL,
        [assembled_by]            NVARCHAR(128) NULL,
        [disassembled_by]         NVARCHAR(128) NULL,
        [test_length_h]           FLOAT         NULL,
        [protocol]                NVARCHAR(256) NULL,
        [format]                  NVARCHAR(64)  NULL,
        [experiment_finished_on]  DATE          NULL,
        [notes]                   NVARCHAR(MAX) NULL,
        [archived_in]             NVARCHAR(256) NULL,
        [plot]                    NVARCHAR(512) NULL,
        [synthesis_recipe]        NVARCHAR(256) NULL,
        [synthesis_time_h]        FLOAT         NULL,
        [synthesis_temperature_c] FLOAT         NULL,
        [coating_test_on]         NVARCHAR(64)  NULL,
        [created_at]              DATETIME2     NOT NULL
                                  CONSTRAINT [DF_ic_logbook_created] DEFAULT SYSUTCDATETIME(),
        [updated_at]              DATETIME2     NULL
    );

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_ic_logbook_category'
                 AND object_id = OBJECT_ID(N'[icm].[ic_logbook]'))
    CREATE INDEX [IX_ic_logbook_category] ON [icm].[ic_logbook] ([category]);

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_ic_logbook_ic_id'
                 AND object_id = OBJECT_ID(N'[icm].[ic_logbook]'))
    CREATE INDEX [IX_ic_logbook_ic_id] ON [icm].[ic_logbook] ([ic_id]);

-- Scoreboard: manual historical snapshots (date + days are set once, the two
-- values are user-edited).
IF OBJECT_ID(N'[icm].[ic_logbook_scoreboard]', N'U') IS NULL
    CREATE TABLE [icm].[ic_logbook_scoreboard] (
        [id]                   INT IDENTITY(1,1) NOT NULL
                               CONSTRAINT [PK_ic_logbook_scoreboard] PRIMARY KEY,
        [snapshot_date]        DATE  NULL,
        [days_since_intro]     INT   NULL,
        [total_testing_time_h] FLOAT NULL,
        [number_of_ics]        INT   NULL,
        [created_at]           DATETIME2 NOT NULL
                               CONSTRAINT [DF_ic_logbook_sb_created] DEFAULT SYSUTCDATETIME()
    );

-- Insert an experiment. Returns the new id.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_insert]
    @category                NVARCHAR(64)  = NULL,
    @ic_id                   NVARCHAR(256) = NULL,
    @owner                   NVARCHAR(128) = NULL,
    @assembled_by            NVARCHAR(128) = NULL,
    @disassembled_by         NVARCHAR(128) = NULL,
    @test_length_h           FLOAT         = NULL,
    @protocol                NVARCHAR(256) = NULL,
    @format                  NVARCHAR(64)  = NULL,
    @experiment_finished_on  DATE          = NULL,
    @notes                   NVARCHAR(MAX) = NULL,
    @archived_in             NVARCHAR(256) = NULL,
    @plot                    NVARCHAR(512) = NULL,
    @synthesis_recipe        NVARCHAR(256) = NULL,
    @synthesis_time_h        FLOAT         = NULL,
    @synthesis_temperature_c FLOAT         = NULL,
    @coating_test_on         NVARCHAR(64)  = NULL,
    @id                      INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[ic_logbook]
        ([category],[ic_id],[owner],[assembled_by],[disassembled_by],[test_length_h],
         [protocol],[format],[experiment_finished_on],[notes],[archived_in],[plot],
         [synthesis_recipe],[synthesis_time_h],[synthesis_temperature_c],[coating_test_on])
    VALUES
        (@category,@ic_id,@owner,@assembled_by,@disassembled_by,@test_length_h,
         @protocol,@format,@experiment_finished_on,@notes,@archived_in,@plot,
         @synthesis_recipe,@synthesis_time_h,@synthesis_temperature_c,@coating_test_on);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Update an experiment by id.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_update]
    @id                      INT,
    @category                NVARCHAR(64)  = NULL,
    @ic_id                   NVARCHAR(256) = NULL,
    @owner                   NVARCHAR(128) = NULL,
    @assembled_by            NVARCHAR(128) = NULL,
    @disassembled_by         NVARCHAR(128) = NULL,
    @test_length_h           FLOAT         = NULL,
    @protocol                NVARCHAR(256) = NULL,
    @format                  NVARCHAR(64)  = NULL,
    @experiment_finished_on  DATE          = NULL,
    @notes                   NVARCHAR(MAX) = NULL,
    @archived_in             NVARCHAR(256) = NULL,
    @plot                    NVARCHAR(512) = NULL,
    @synthesis_recipe        NVARCHAR(256) = NULL,
    @synthesis_time_h        FLOAT         = NULL,
    @synthesis_temperature_c FLOAT         = NULL,
    @coating_test_on         NVARCHAR(64)  = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[ic_logbook]
       SET [category]                = @category,
           [ic_id]                   = @ic_id,
           [owner]                   = @owner,
           [assembled_by]            = @assembled_by,
           [disassembled_by]         = @disassembled_by,
           [test_length_h]           = @test_length_h,
           [protocol]                = @protocol,
           [format]                  = @format,
           [experiment_finished_on]  = @experiment_finished_on,
           [notes]                   = @notes,
           [archived_in]             = @archived_in,
           [plot]                    = @plot,
           [synthesis_recipe]        = @synthesis_recipe,
           [synthesis_time_h]        = @synthesis_time_h,
           [synthesis_temperature_c] = @synthesis_temperature_c,
           [coating_test_on]         = @coating_test_on,
           [updated_at]              = SYSUTCDATETIME()
     WHERE [id] = @id;

    IF @@ROWCOUNT = 0
        THROW 50000, N''IC logbook row not found for the given id.'', 1;
END
');

-- Delete an experiment by id.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[ic_logbook] WHERE [id] = @id;
    IF @@ROWCOUNT = 0
        THROW 50000, N''IC logbook row not found for the given id.'', 1;
END
');

-- Insert a scoreboard snapshot. Returns the new id.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_scoreboard_insert]
    @snapshot_date        DATE  = NULL,
    @days_since_intro     INT   = NULL,
    @total_testing_time_h FLOAT = NULL,
    @number_of_ics        INT   = NULL,
    @id                   INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO [icm].[ic_logbook_scoreboard]
        ([snapshot_date],[days_since_intro],[total_testing_time_h],[number_of_ics])
    VALUES (@snapshot_date,@days_since_intro,@total_testing_time_h,@number_of_ics);
    SET @id = CAST(SCOPE_IDENTITY() AS INT);
END
');

-- Update a scoreboard snapshot''s two manual values by id (date/days are fixed).
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_scoreboard_update]
    @id                   INT,
    @total_testing_time_h FLOAT = NULL,
    @number_of_ics        INT   = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE [icm].[ic_logbook_scoreboard]
       SET [total_testing_time_h] = @total_testing_time_h,
           [number_of_ics]        = @number_of_ics
     WHERE [id] = @id;
    IF @@ROWCOUNT = 0
        THROW 50000, N''Scoreboard snapshot not found for the given id.'', 1;
END
');

-- Delete a scoreboard snapshot by id.
EXEC (N'
CREATE OR ALTER PROCEDURE [icm].[usp_ic_logbook_scoreboard_delete]
    @id INT
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM [icm].[ic_logbook_scoreboard] WHERE [id] = @id;
    IF @@ROWCOUNT = 0
        THROW 50000, N''Scoreboard snapshot not found for the given id.'', 1;
END
');

GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_insert]            TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_update]            TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_delete]            TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_scoreboard_insert] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_scoreboard_update] TO [ic_manager_role];
GRANT EXECUTE ON OBJECT::[icm].[usp_ic_logbook_scoreboard_delete] TO [ic_manager_role];

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'017_create_ic_logbook_tables_and_procs.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'017_create_ic_logbook_tables_and_procs.sql');
GO
