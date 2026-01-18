#!/bin/bash
# reload-workers.sh - Restart all clerk worker LaunchAgents
# Uses launchctl kickstart to restart workers without unloading/reloading
# Useful for deploying code changes quickly

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# LaunchAgents directory
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"

# Find all clerk worker plist files
WORKER_PLISTS=($(find "${LAUNCHAGENTS_DIR}" -name "com.civicband.clerk.worker.*.plist" 2>/dev/null || true))

if [ ${#WORKER_PLISTS[@]} -eq 0 ]; then
    echo -e "${RED}Error: No clerk worker LaunchAgents found.${NC}"
    echo ""
    echo "Looking in: ${LAUNCHAGENTS_DIR}"
    echo "Pattern: com.civicband.clerk.worker.*.plist"
    echo ""
    echo "Run 'clerk install-workers' to install workers first."
    exit 1
fi

echo "Reloading clerk workers..."
echo ""
echo "Found ${#WORKER_PLISTS[@]} worker(s) to reload"
echo ""

# Counters
RELOADED=0
FAILED=0

# Reload each worker using kickstart
for plist in "${WORKER_PLISTS[@]}"; do
    label=$(basename "$plist" .plist)

    # Use kickstart -k to kill and restart the service
    # This forces the worker to restart immediately with new code
    if launchctl kickstart -k "gui/$(id -u)/${label}" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Reloaded: ${label}"
        RELOADED=$((RELOADED + 1))
    else
        echo -e "${RED}✗${NC} Failed to reload: ${label}"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
if [ ${FAILED} -eq 0 ]; then
    echo -e "${GREEN}Reload complete!${NC}"
else
    echo -e "${YELLOW}Reload completed with errors${NC}"
fi
echo ""
echo "Summary:"
echo "  Reloaded: ${RELOADED}"
if [ ${FAILED} -gt 0 ]; then
    echo -e "  ${RED}Failed: ${FAILED}${NC}"
fi
echo ""

echo "Workers have been restarted and are now running with updated code."
echo ""
echo "To check worker status:"
echo "  launchctl list | grep com.civicband.clerk.worker"
echo ""
echo "To view logs:"
echo "  tail -f ~/.clerk/logs/clerk-worker-*.log"
echo ""
