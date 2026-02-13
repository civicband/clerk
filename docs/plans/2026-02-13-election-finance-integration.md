# Election Finance Data Integration Plan

## Overview
This document serves as the parent plan for integrating California election finance data from the Netfile API into the civic.band data pipeline. The integration will be implemented as a plugin architecture where `election-finance` becomes a pip-installable package that provides clerk plugin implementations.

## Architecture Design
- **clerk**: Core pipeline framework with enhanced plugin system
- **election-finance**: Standalone Python package with clerk plugin interface
- **corkboard**: Datasette server updated to serve multiple databases
- **civic-band**: Orchestrator that installs all packages and provides configuration

## Repository Changes Overview

### election-finance
See: `election-finance/CLERK_INTEGRATION_PLAN.md`
- Restructure as pip-installable Python package
- Add clerk plugin implementation
- Provide CLI commands and RQ job functions
- Maintain existing ETL logic in CAFinanceETL class

### clerk (this repository)
See: `CLERK_PLUGIN_ENHANCEMENTS.md` (in this directory)
- Add new plugin hookspecs for CLI and job registration
- Update CLI to support plugin-provided commands
- Extend queue system to handle plugin job types
- Add database migration for has_finance_data field

### corkboard
See: `corkboard/MULTI_DATABASE_SUPPORT.md`
- Update datasette_by_subdomain.py to serve multiple databases
- Modify metadata handling for finance database
- Ensure proper URL routing for finance data

### civic-band
See: `civic-band/FINANCE_INTEGRATION.md`
- Update requirements to include election-finance package
- Modify deployment plugin to handle finance databases
- Configure scheduling for finance ETL jobs
- Update sites.db generation

## Data Flow

```
1. Netfile API → election-finance ETL → election_finance.db
   └─ Location: ../sites/{subdomain}/finance/

2. clerk deploy job → Upload both databases
   ├─ meetings.db → {subdomain}.civic.band/meetings/
   └─ election_finance.db → {subdomain}.civic.band/election_finance/

3. corkboard (datasette) → Serve both databases
   └─ Single subdomain serves multiple data types
```

## Database Schema Changes

### sites table (clerk/civic.db)
```sql
ALTER TABLE sites ADD COLUMN has_finance_data BOOLEAN DEFAULT false;
CREATE INDEX idx_sites_has_finance_data ON sites(has_finance_data);
```

## Storage Convention
All repositories will respect the shared storage pattern:
- Base: `{STORAGE_DIR}/{subdomain}/`
- Meetings: `{subdomain}/meetings.db`
- Finance: `{subdomain}/finance/election_finance.db`
- PDFs: `{subdomain}/pdfs/` and `{subdomain}/_agendas/pdfs/`
- OCR Text: `{subdomain}/txt/` and `{subdomain}/_agendas/txt/`

## CLI Interface
After integration, these commands will be available:
```bash
# From civic-band directory
clerk finance etl --all                    # Process all agencies
clerk finance etl --subdomain alameda.ca   # Process specific municipality
clerk finance extract [subdomain]          # Extract stage only
clerk finance transform [subdomain]        # Transform stage only
clerk finance load [subdomain]            # Load stage only
```

## Scheduling
Daily cron job for finance updates (matching Netfile's daily refresh):
```cron
0 6 * * * cd /path/to/civic-band && clerk finance etl --next-site
```

## Implementation Phases

### Phase 1: Package Restructuring (election-finance)
- Convert to standard Python package structure
- Add clerk as dependency
- Create plugin interface module

### Phase 2: Plugin System Enhancement (clerk)
- Add new hookspecs for CLI and job registration
- Update CLI to discover and register plugin commands
- Extend queue system for plugin job types

### Phase 3: Multi-Database Support (corkboard)
- Update datasette configuration for multiple databases
- Modify subdomain routing logic
- Test with both meetings and finance databases

### Phase 4: Integration & Deployment (civic-band)
- Add election-finance to requirements
- Update deployment scripts
- Configure and test end-to-end flow

### Phase 5: Rollout
- Generate agency-to-site mapping file
- Test with 5 pilot cities
- Gradual rollout to all CA municipalities

## Success Criteria
- ✅ Finance data accessible at `{subdomain}.civic.band/election_finance/`
- ✅ Both meetings and finance databases served from single subdomain
- ✅ Daily automatic updates via cron
- ✅ Clean plugin architecture with separation of concerns
- ✅ No disruption to existing meeting data pipeline
- ✅ Scalable to 100+ California municipalities

## Testing Strategy
1. Unit tests in each repository for new functionality
2. Integration tests for plugin discovery and registration
3. End-to-end tests with pilot municipalities
4. Performance testing with full dataset
5. Deployment verification on staging environment

## Rollout Plan
1. **Week 1**: Implement changes across all repositories
2. **Week 2**: Test with 5 pilot cities (alameda.ca, berkeley.ca, oakland.ca, alameda-county.ca, san-francisco.ca)
3. **Week 3**: Add 10 additional cities, monitor performance
4. **Week 4**: Complete rollout to all CA municipalities

## Risk Mitigation
- Separate worker queues prevent blocking
- Phased rollout for early issue detection
- Database separation maintains independence
- Backward compatibility maintained for existing pipeline
- Manual mapping review ensures correct associations

## Monitoring & Observability
- Finance ETL jobs logged to existing Loki instance
- Job success/failure tracked in job_tracking table
- Database sizes monitored for growth
- Daily update success rate dashboard
- Error alerting for failed ETL jobs

## Documentation Updates Needed
1. clerk README: Document new plugin hookspecs
2. election-finance README: Installation and usage as clerk plugin
3. civic-band deployment docs: Finance data configuration
4. corkboard docs: Multi-database serving

## Contact
Project Lead: [TBD]
Technical Questions: [TBD]

## Related Documents
- `election-finance/CLERK_INTEGRATION_PLAN.md` - Finance package changes
- `clerk/CLERK_PLUGIN_ENHANCEMENTS.md` - Plugin system enhancements
- `corkboard/MULTI_DATABASE_SUPPORT.md` - Datasette multi-DB support
- `civic-band/FINANCE_INTEGRATION.md` - Orchestration and deployment