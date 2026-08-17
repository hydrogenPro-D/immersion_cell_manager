-- reset_dev.sql
-- DEV/TEST RESET, drops the icm domain tables so the (edited) migrations
-- 004-006 can recreate them with the new surrogate-id schema.
--
-- *** DESTRUCTIVE: deletes ALL rows in projects / cells / channel_history. ***
--
-- This is NOT a numbered migration. It is guarded to run ONLY on
-- dataloggingTest; it THROWS on dataloggingDev (or any other database).
--
-- After running this, re-run migrations 004, 005, 006 (in order) to rebuild the
-- tables. The stored procedures (007-009) re-resolve against the new tables
-- automatically, and the ledger rows / grants stay intact.

IF DB_NAME() <> N'dataloggingTest'
    THROW 50000, N'reset_dev.sql runs ONLY on dataloggingTest. Aborting.', 1;

-- Drop children first: cells and channel_history hold FKs to projects, so the
-- parent cannot be dropped while they still exist.
DROP TABLE IF EXISTS [icm].[channel_history];
DROP TABLE IF EXISTS [icm].[cells];
DROP TABLE IF EXISTS [icm].[projects];
GO
