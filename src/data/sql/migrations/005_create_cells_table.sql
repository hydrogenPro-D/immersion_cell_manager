-- 005_create_cells_table.sql
-- One row per immersion-cell channel (current state). Mirrors immersion_cells.csv.
--
-- NOTE: 'duration' is intentionally NOT a column. The app computes it at runtime
-- from start_date + start_hour, so there is nothing to store.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF OBJECT_ID(N'[icm].[schema_migrations]', N'U') IS NULL
    THROW 50000, N'Run 001 first (creates the schema + ledger).', 1;

IF OBJECT_ID(N'[icm].[cells]', N'U') IS NULL
    CREATE TABLE [icm].[cells] (
        [id]            INT IDENTITY(1,1) NOT NULL
                        CONSTRAINT [PK_cells] PRIMARY KEY,
        -- channel is the business key (e.g. '1-1'); UNIQUE so it can't repeat.
        [channel]       NVARCHAR(32)  NOT NULL
                        CONSTRAINT [UQ_cells_channel] UNIQUE,
        [status]        NVARCHAR(32)  NULL,                  -- 'Available', 'In use', ...
        [project_id]    NVARCHAR(128) NULL,
        [current_owner] NVARCHAR(256) NULL,
        [assembled_by]  NVARCHAR(256) NULL,
        [start_date]    DATE          NULL,
        [start_hour]    TINYINT       NULL,                  -- 0..23
        [cathode]       NVARCHAR(256) NULL,
        [anode]         NVARCHAR(256) NULL,
        [data_filename] NVARCHAR(256) NULL,
        [added_water_b] NVARCHAR(64)  NULL,                  -- 'Added water by timing'
        [comments]      NVARCHAR(MAX) NULL,
        [separator]     NVARCHAR(128) NULL,
        CONSTRAINT [FK_cells_project] FOREIGN KEY ([project_id])
            REFERENCES [icm].[projects] ([project_id])
            ON UPDATE CASCADE     -- project rename flows through automatically
            ON DELETE SET NULL    -- project delete clears the reference
    );

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'005_create_cells_table.sql')
    INSERT INTO [icm].[schema_migrations] (filename)
    VALUES (N'005_create_cells_table.sql');
GO
