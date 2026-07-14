\pset tuples_only on
\pset format unaligned
\pset fieldsep '|'

BEGIN TRANSACTION READ ONLY;

SELECT 'snapshot', clock_timestamp();

SELECT
    'server',
    current_setting('server_version'),
    current_database(),
    pg_size_pretty(pg_database_size(current_database()));

SELECT
    'database',
    numbackends,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit,
    temp_files,
    temp_bytes,
    deadlocks,
    stats_reset
FROM pg_stat_database
WHERE datname = current_database();

SELECT
    'connections',
    COALESCE(state, 'unknown'),
    count(*)
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY COALESCE(state, 'unknown')
ORDER BY COALESCE(state, 'unknown');

SELECT
    'waiting_locks',
    count(*)
FROM pg_locks
WHERE NOT granted
  AND (
      database IS NULL
      OR database = (
          SELECT oid
          FROM pg_database
          WHERE datname = current_database()
      )
  );

SELECT
    'user_tables',
    count(*),
    COALESCE(sum(n_live_tup), 0),
    COALESCE(sum(n_dead_tup), 0),
    COALESCE(sum(seq_scan), 0),
    COALESCE(sum(idx_scan), 0)
FROM pg_stat_user_tables;

SELECT
    'io_tracking',
    current_setting('track_io_timing'),
    current_setting('track_wal_io_timing');

SELECT
    'io',
    COALESCE(sum(reads), 0),
    COALESCE(sum(writes), 0),
    COALESCE(sum(writebacks), 0),
    COALESCE(sum(extends), 0),
    COALESCE(sum(hits), 0),
    COALESCE(sum(evictions), 0),
    COALESCE(sum(fsyncs), 0),
    min(stats_reset)
FROM pg_stat_io;

SELECT
    'wal',
    wal_records,
    wal_fpi,
    wal_bytes,
    wal_buffers_full,
    wal_write,
    wal_sync,
    stats_reset
FROM pg_stat_wal;

SELECT
    'checkpointer',
    num_timed,
    num_requested,
    restartpoints_timed,
    restartpoints_req,
    restartpoints_done,
    buffers_written,
    stats_reset
FROM pg_stat_checkpointer;

SELECT (
    EXISTS (
        SELECT 1
        FROM unnest(
            string_to_array(current_setting('shared_preload_libraries'), ',')
        ) AS preload_library(name)
        WHERE btrim(name) = 'pg_stat_statements'
    )
    AND
    EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'pg_stat_statements'
    )
) AS pg_stat_statements_ready
\gset

SELECT 'pg_stat_statements', :'pg_stat_statements_ready';

\if :pg_stat_statements_ready
SELECT
    'statement_totals',
    COALESCE(sum(calls), 0),
    COALESCE(sum(total_exec_time), 0),
    CASE
        WHEN COALESCE(sum(calls), 0) = 0 THEN 0
        ELSE sum(total_exec_time) / sum(calls)
    END,
    COALESCE(sum(rows), 0),
    COALESCE(sum(shared_blks_read), 0),
    COALESCE(sum(temp_blks_read), 0),
    COALESCE(sum(temp_blks_written), 0)
FROM pg_stat_statements
WHERE dbid = (
    SELECT oid
    FROM pg_database
    WHERE datname = current_database()
);

SELECT
    'statement_top',
    queryid,
    calls,
    total_exec_time,
    mean_exec_time,
    rows,
    shared_blks_read,
    temp_blks_read,
    temp_blks_written
FROM pg_stat_statements
WHERE dbid = (
    SELECT oid
    FROM pg_database
    WHERE datname = current_database()
)
ORDER BY total_exec_time DESC
LIMIT 20;

SELECT 'statement_stats_reset', stats_reset
FROM pg_stat_statements_info;
\endif

COMMIT;
