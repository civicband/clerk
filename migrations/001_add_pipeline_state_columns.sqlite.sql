-- Pipeline State Consolidation Migration (SQLite version)
-- Adds atomic counter columns to sites table

-- Pipeline state tracking
ALTER TABLE sites ADD COLUMN current_stage VARCHAR;
ALTER TABLE sites ADD COLUMN started_at TIMESTAMP;
ALTER TABLE sites ADD COLUMN updated_at TIMESTAMP;

-- Fetch stage counters
ALTER TABLE sites ADD COLUMN fetch_total INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN fetch_completed INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN fetch_failed INTEGER DEFAULT 0;

-- OCR stage counters
ALTER TABLE sites ADD COLUMN ocr_total INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN ocr_completed INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN ocr_failed INTEGER DEFAULT 0;

-- Compilation stage counters
ALTER TABLE sites ADD COLUMN compilation_total INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN compilation_completed INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN compilation_failed INTEGER DEFAULT 0;

-- Extraction stage counters
ALTER TABLE sites ADD COLUMN extraction_total INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN extraction_completed INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN extraction_failed INTEGER DEFAULT 0;

-- Deploy stage counters
ALTER TABLE sites ADD COLUMN deploy_total INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN deploy_completed INTEGER DEFAULT 0;
ALTER TABLE sites ADD COLUMN deploy_failed INTEGER DEFAULT 0;

-- Coordinator tracking
ALTER TABLE sites ADD COLUMN coordinator_enqueued BOOLEAN DEFAULT 0;

-- Error observability
ALTER TABLE sites ADD COLUMN last_error_stage VARCHAR;
ALTER TABLE sites ADD COLUMN last_error_message TEXT;
ALTER TABLE sites ADD COLUMN last_error_at TIMESTAMP;

-- Indexes for performance
CREATE INDEX idx_sites_current_stage ON sites(current_stage);
CREATE INDEX idx_sites_updated_at ON sites(updated_at);
CREATE INDEX idx_sites_coordinator_enqueued ON sites(subdomain, coordinator_enqueued) WHERE coordinator_enqueued = 0;
