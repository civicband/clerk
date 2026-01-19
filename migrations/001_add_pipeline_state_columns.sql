-- Pipeline State Consolidation Migration
-- Adds atomic counter columns to sites table

-- Pipeline state tracking
ALTER TABLE sites ADD COLUMN IF NOT EXISTS current_stage VARCHAR;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Fetch stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_failed INT DEFAULT 0;

-- OCR stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_failed INT DEFAULT 0;

-- Compilation stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_failed INT DEFAULT 0;

-- Extraction stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_failed INT DEFAULT 0;

-- Deploy stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_failed INT DEFAULT 0;

-- Coordinator tracking
ALTER TABLE sites ADD COLUMN IF NOT EXISTS coordinator_enqueued BOOLEAN DEFAULT FALSE;

-- Error observability
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_stage VARCHAR;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_message TEXT;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMP;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sites_current_stage ON sites(current_stage);
CREATE INDEX IF NOT EXISTS idx_sites_updated_at ON sites(updated_at);
CREATE INDEX IF NOT EXISTS idx_sites_coordinator_enqueued ON sites(subdomain, coordinator_enqueued) WHERE coordinator_enqueued = FALSE;

-- Comments for documentation
COMMENT ON COLUMN sites.current_stage IS 'Current pipeline stage: fetch|ocr|compilation|extraction|deploy|completed';
COMMENT ON COLUMN sites.coordinator_enqueued IS 'Prevents duplicate coordinators - atomically claimed by last job';
