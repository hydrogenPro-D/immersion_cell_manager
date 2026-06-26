-- 006_create_channel_history_table.sql
-- Log of experiment episodes per channel. Mirrors station_history.json
-- (a list of episodes keyed by channel).
--
-- A surrogate [id] is the PK because episodes have no natural key.
--
-- NOTE: [channel] is intentionally NOT a foreign key to [icm].[cells]. Today the
-- app keeps a channel's history even after its cell is deleted; a hard FK would
-- block that delete (or cascade-delete the history). Add one later if desired.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[channel_history]', N'U') IS NULL
    CREATE TABLE [icm].[channel_history] (
        [id]                     INT IDENTITY(1,1) NOT NULL
                                 CONSTRAINT [PK_channel_history] PRIMARY KEY,
        [channel]                NVARCHAR(32)  NOT NULL,
        [project_id]             NVARCHAR(128) NULL,
        [current_owner]          NVARCHAR(256) NULL,
        [assembled_by]           NVARCHAR(256) NULL,
        [status]                 NVARCHAR(32)  NULL,
        [start_date]             DATE          NULL,
        [start_hour]             TINYINT       NULL,
        [end_date]               DATE          NULL,
        [cathode]                NVARCHAR(256) NULL,
        [anode]                  NVARCHAR(256) NULL,
        [data_filename]          NVARCHAR(256) NULL,
        [original_data_filename] NVARCHAR(256) NULL,  -- JSON '__original_data_filename'
        [added_water_b]          NVARCHAR(64)  NULL,
        [comments]               NVARCHAR(MAX) NULL,
        [separator]              NVARCHAR(128) NULL,
        CONSTRAINT [FK_history_project] FOREIGN KEY ([project_id])
            REFERENCES [icm].[projects] ([project_id])
            ON UPDATE CASCADE
            ON DELETE SET NULL
    );

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'006_create_channel_history_table.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'006_create_channel_history_table.sql');
GO
