-- Grafana Dashboard Query Validation
-- Run this against your civic.db to verify all queries work
-- Usage: psql $DATABASE_URL -f deployment/grafana/test-queries.sql

\echo '==================================='
\echo 'Panel 1.1: Stuck Sites Count'
\echo '==================================='

SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours'
  AND updated_at > NOW() - INTERVAL '24 hours';

\echo ''
\echo '==================================='
\echo 'Panel 1.2: Health Score'
\echo '==================================='

SELECT ROUND(100.0 *
    COUNT(*) FILTER (
        WHERE current_stage = 'completed'
           OR updated_at >= NOW() - INTERVAL '2 hours'
    ) / NULLIF(COUNT(*), 0),
1) as health_score
FROM sites
WHERE current_stage IS NOT NULL
  AND started_at > NOW() - INTERVAL '24 hours';

\echo ''
\echo '==================================='
\echo 'Panel 1.3: Stage Distribution'
\echo '==================================='

SELECT
    current_stage,
    COUNT(*) as count
FROM sites
WHERE current_stage IS NOT NULL
  AND updated_at > NOW() - INTERVAL '24 hours'
GROUP BY current_stage
ORDER BY count DESC;

\echo ''
\echo '==================================='
\echo 'Panel 2.1: Completions per Hour'
\echo '==================================='

SELECT
    DATE_TRUNC('hour', updated_at) as time,
    COUNT(*) as completions
FROM sites
WHERE current_stage = 'completed'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND updated_at <= NOW()
GROUP BY time
ORDER BY time DESC
LIMIT 5;

\echo ''
\echo '==================================='
\echo 'Panel 2.2: OCR Failure Rate'
\echo '==================================='

SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'ocr' as stage,
    ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND updated_at >= NOW() - INTERVAL '24 hours'
GROUP BY time
ORDER BY time DESC
LIMIT 5;

\echo ''
\echo '==================================='
\echo 'Panel 2.3: Avg Time in Stage'
\echo '==================================='

SELECT
    current_stage as stage,
    AVG(EXTRACT(EPOCH FROM (updated_at - started_at))/3600) as avg_hours
FROM sites
WHERE started_at IS NOT NULL
  AND updated_at > NOW() - INTERVAL '24 hours'
  AND current_stage IS NOT NULL
GROUP BY current_stage
ORDER BY avg_hours DESC;

\echo ''
\echo '==================================='
\echo 'Variable 2: Subdomain List'
\echo '==================================='

SELECT DISTINCT subdomain
FROM sites
WHERE updated_at > NOW() - INTERVAL '24 hours'
ORDER BY subdomain
LIMIT 10;

\echo ''
\echo '==================================='
\echo 'Alert 1: Stuck Sites (Critical)'
\echo '==================================='

SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours';

\echo ''
\echo 'If stuck_count > 10: CRITICAL ALERT'
\echo ''

\echo '==================================='
\echo 'Alert 2: Health Score (Warning)'
\echo '==================================='

SELECT ROUND(100.0 *
    COUNT(*) FILTER (
        WHERE current_stage = 'completed'
           OR updated_at >= NOW() - INTERVAL '2 hours'
    ) / NULLIF(COUNT(*), 0),
1) as health_score
FROM sites
WHERE current_stage IS NOT NULL
  AND started_at > NOW() - INTERVAL '24 hours';

\echo ''
\echo 'If health_score < 85: WARNING ALERT'
\echo ''

\echo '==================================='
\echo 'Alert 3: OCR Failure Rate (Warning)'
\echo '==================================='

SELECT
    'ocr' as stage,
    ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND updated_at >= NOW() - INTERVAL '1 hour';

\echo ''
\echo 'If failure_rate > 20: WARNING ALERT'
\echo ''

\echo '==================================='
\echo 'All queries completed successfully!'
\echo '==================================='
