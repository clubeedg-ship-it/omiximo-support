-- Reclaim audit_log bloat.
--
-- Background: a previous version of app/services/collector.py wrote one
-- `message_filtered` audit row for every noise message on every poll cycle.
-- With no dedup and autovacuum effectively never running, audit_log grew to
-- ~43.4M rows / ~18GB on a system with ~124 real threads. The collector no
-- longer writes those rows (it logs at DEBUG instead), but the historical rows
-- remain. This script removes them and reclaims the space.
--
-- Usage (psql connected to omiximo_support):
--   \i prune_audit_log.sql
--
-- Note: VACUUM FULL takes an ACCESS EXCLUSIVE lock and needs free disk roughly
-- equal to the live table size. The clean PVC migration in k8s/README.md avoids
-- this entirely by restoring the DB WITHOUT these rows; run this script only
-- when pruning an existing database in place.

\timing on

-- 1. Drop the historical spam. Legitimate audit actions are untouched.
DELETE FROM audit_log WHERE action = 'message_filtered';

-- 2. Reclaim disk and refresh planner statistics.
VACUUM (FULL, ANALYZE) audit_log;

-- 3. Make this table self-maintaining so it can never balloon again:
--    vacuum/analyze aggressively on inserts.
ALTER TABLE audit_log SET (
    autovacuum_vacuum_insert_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02
);

-- 4. Index used by the retention job and time-range reporting.
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at);
