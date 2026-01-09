#!/bin/bash
# uninstall-workers.sh - Remove all clerk worker LaunchAgents
# Unloads and removes all com.civicband.clerk.worker.* plist files

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
    echo -e "${YELLOW}No clerk worker LaunchAgents found.${NC}"
    echo ""
    echo "Looking in: ${LAUNCHAGENTS_DIR}"
    echo "Pattern: com.civicband.clerk.worker.*.plist"
    echo ""
    exit 0
fi

echo "Uninstalling clerk workers..."
echo ""
echo "Found ${#WORKER_PLISTS[@]} worker(s) to remove:"
echo ""

# Show what will be removed
for plist in "${WORKER_PLISTS[@]}"; do
    basename "$plist"
done

echo ""
read -p "Continue with uninstall? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 0
fi

echo ""
echo "Unloading and removing workers..."
echo ""

# Counters
UNLOADED=0
REMOVED=0
FAILED=0

# Unload and remove each plist
for plist in "${WORKER_PLISTS[@]}"; do
    label=$(basename "$plist" .plist)

    # Try to unload
    if launchctl unload "$plist" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Unloaded: ${label}"
        UNLOADED=$((UNLOADED + 1))
    else
        # It's OK if unload fails (worker might not be loaded)
        echo -e "${YELLOW}○${NC} Not loaded: ${label}"
    fi

    # Remove plist file
    if rm "$plist" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Removed: ${label}"
        REMOVED=$((REMOVED + 1))
    else
        echo -e "${RED}✗${NC} Failed to remove: ${label}"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo -e "${GREEN}Uninstall complete!${NC}"
echo ""
echo "Summary:"
echo "  Unloaded: ${UNLOADED}"
echo "  Removed: ${REMOVED}"
if [ ${FAILED} -gt 0 ]; then
    echo -e "  ${RED}Failed: ${FAILED}${NC}"
fi
echo ""

# Check if any workers are still running
RUNNING_WORKERS=$(launchctl list | grep "com.civicband.clerk.worker" || true)
if [ -n "$RUNNING_WORKERS" ]; then
    echo -e "${YELLOW}Warning: Some workers may still be running:${NC}"
    echo "$RUNNING_WORKERS"
    echo ""
    echo "To manually stop them, run:"
    echo "  launchctl remove <label>"
    echo ""
else
    echo "All workers have been stopped and removed."
    echo ""
fi

# Note about logs
echo "Note: Log files in ~/.clerk/logs/ have not been removed."
echo "To clean up logs, run:"
echo "  rm -rf ~/.clerk/logs/"
echo ""
