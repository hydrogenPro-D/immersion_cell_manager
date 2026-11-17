-- undo_import_calibration_history.sql  (maintenance, not a migration)
-- Removes exactly the rows import_calibration_history.sql added on production:
-- decided by 'Excel import' AND newer than the last calibration that existed
-- before the import (id 49 on dataloggingDev, 2026-11-17). Rows entered in the
-- app are never 'Excel import', and older ones are below the id limit.
-- Run with an admin login. Shows how many rows it removed.

IF DB_NAME() <> N'dataloggingDev'
    THROW 50000, N'This undo is for dataloggingDev only (its id limit is production''s).', 1;

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @last_id_before_import INT = 49;

BEGIN TRAN;
DELETE FROM [icm].[channel_calibration]
 WHERE [decided_by] = N'Excel import'
   AND [id] > @last_id_before_import;
DECLARE @removed INT = @@ROWCOUNT;
COMMIT;

SELECT @removed AS removed,
       (SELECT COUNT(*) FROM [icm].[channel_calibration]) AS rows_left;  -- expect 47
GO
