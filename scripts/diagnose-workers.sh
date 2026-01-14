#!/bin/bash
# diagnose-workers.sh - Diagnose why clerk workers are failing to load
# Run this on the production machine to identify the issue

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Clerk Worker Diagnostics ===${NC}"
echo ""

# 1. Check if .env exists
echo -e "${BLUE}1. Checking .env file...${NC}"
if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
    echo "   Location: $(pwd)/.env"
else
    echo -e "${RED}✗${NC} .env file not found"
    echo "   Workers need .env file in the working directory"
fi
echo ""

# 2. Check if clerk executable exists and is executable
echo -e "${BLUE}2. Checking clerk executable...${NC}"
CLERK_PATH=$(which clerk 2>/dev/null || echo "")
if [ -z "${CLERK_PATH}" ]; then
    if [ -d ".venv/bin" ]; then
        CLERK_PATH="$(pwd)/.venv/bin/clerk"
    elif [ -d "venv/bin" ]; then
        CLERK_PATH="$(pwd)/venv/bin/clerk"
    fi
fi

if [ -n "${CLERK_PATH}" ] && [ -x "${CLERK_PATH}" ]; then
    echo -e "${GREEN}✓${NC} Clerk executable found and executable"
    echo "   Path: ${CLERK_PATH}"
    echo "   Version: $(${CLERK_PATH} --version 2>&1 || echo 'unknown')"
else
    echo -e "${RED}✗${NC} Clerk executable not found or not executable"
    if [ -n "${CLERK_PATH}" ]; then
        echo "   Path checked: ${CLERK_PATH}"
    fi
fi
echo ""

# 3. Check Redis connection
echo -e "${BLUE}3. Checking Redis connection...${NC}"
if [ -f ".env" ]; then
    source .env
    REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
    echo "   Redis URL: ${REDIS_URL}"

    # Try to connect using redis-cli or Python
    if command -v redis-cli &> /dev/null; then
        # Extract host and port from REDIS_URL
        REDIS_HOST=$(echo $REDIS_URL | sed -n 's|redis://\([^:]*\).*|\1|p')
        REDIS_PORT=$(echo $REDIS_URL | sed -n 's|redis://[^:]*:\([0-9]*\).*|\1|p')
        REDIS_PORT="${REDIS_PORT:-6379}"

        if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping &> /dev/null; then
            echo -e "${GREEN}✓${NC} Redis is running and accessible"
        else
            echo -e "${RED}✗${NC} Cannot connect to Redis"
            echo "   This is likely why workers are failing!"
        fi
    else
        echo -e "${YELLOW}⚠${NC}  redis-cli not found, trying Python check..."
        if [ -n "${CLERK_PATH}" ] && [ -x "${CLERK_PATH}" ]; then
            if ${CLERK_PATH} --help &> /dev/null; then
                echo -e "${YELLOW}⚠${NC}  Cannot test Redis without redis-cli, but clerk is working"
            fi
        fi
    fi
else
    echo -e "${YELLOW}⚠${NC}  Skipping (no .env file)"
fi
echo ""

# 4. Check log directory
echo -e "${BLUE}4. Checking log directory...${NC}"
LOG_DIR="${HOME}/.clerk/logs"
if [ -d "${LOG_DIR}" ]; then
    echo -e "${GREEN}✓${NC} Log directory exists"
    echo "   Path: ${LOG_DIR}"

    # Show recent errors
    echo ""
    echo "   Recent worker error logs:"
    for logfile in "${LOG_DIR}"/clerk-worker-*.error.log; do
        if [ -f "$logfile" ]; then
            filename=$(basename "$logfile")
            size=$(wc -c < "$logfile")
            if [ $size -gt 0 ]; then
                echo -e "   ${YELLOW}→${NC} $filename (${size} bytes)"
                echo "      Last 5 lines:"
                tail -5 "$logfile" | sed 's/^/        /'
            fi
        fi
    done
else
    echo -e "${YELLOW}⚠${NC}  Log directory doesn't exist: ${LOG_DIR}"
fi
echo ""

# 5. Check plist files
echo -e "${BLUE}5. Checking LaunchAgent plists...${NC}"
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_COUNT=$(ls -1 "${LAUNCHAGENTS_DIR}"/com.civicband.clerk.worker.*.plist 2>/dev/null | wc -l)

if [ $PLIST_COUNT -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found ${PLIST_COUNT} worker plist files"

    # Check one plist for validity
    SAMPLE_PLIST=$(ls -1 "${LAUNCHAGENTS_DIR}"/com.civicband.clerk.worker.*.plist 2>/dev/null | head -1)
    echo "   Sample plist: $(basename "$SAMPLE_PLIST")"

    # Validate XML
    if plutil -lint "$SAMPLE_PLIST" &> /dev/null; then
        echo -e "   ${GREEN}✓${NC} Plist XML is valid"
    else
        echo -e "   ${RED}✗${NC} Plist XML is invalid!"
        plutil -lint "$SAMPLE_PLIST"
    fi

    # Check if workers are loaded
    echo ""
    echo "   Worker status:"
    launchctl list | grep "com.civicband.clerk.worker" | while read -r line; do
        pid=$(echo "$line" | awk '{print $1}')
        status=$(echo "$line" | awk '{print $2}')
        label=$(echo "$line" | awk '{print $3}')

        if [ "$pid" = "-" ]; then
            echo -e "   ${RED}✗${NC} $label (not running, exit code: $status)"
        else
            echo -e "   ${GREEN}✓${NC} $label (PID: $pid)"
        fi
    done
else
    echo -e "${RED}✗${NC} No worker plist files found"
fi
echo ""

# 6. Try running worker manually
echo -e "${BLUE}6. Testing manual worker execution...${NC}"
if [ -n "${CLERK_PATH}" ] && [ -x "${CLERK_PATH}" ]; then
    echo "   Running: ${CLERK_PATH} worker fetch --burst"
    echo "   (This will exit immediately if queue is empty)"
    echo ""

    if ${CLERK_PATH} worker fetch --burst 2>&1; then
        echo ""
        echo -e "${GREEN}✓${NC} Worker can run manually (check output above for Redis errors)"
    else
        echo ""
        echo -e "${RED}✗${NC} Worker failed when run manually (see error above)"
        echo "   This is likely the same error preventing LaunchAgents from loading"
    fi
else
    echo -e "${YELLOW}⚠${NC}  Cannot test (clerk not found)"
fi
echo ""

# 7. Summary and recommendations
echo -e "${BLUE}=== Summary and Recommendations ===${NC}"
echo ""

if [ ! -f ".env" ]; then
    echo -e "${RED}→${NC} Create a .env file in $(pwd)"
fi

# Check for common issues
HAS_ERRORS=0

# Check recent error logs for Redis connection errors
if [ -d "${LOG_DIR}" ]; then
    if grep -r "Cannot connect to Redis" "${LOG_DIR}"/*.error.log 2>/dev/null | head -1 &> /dev/null; then
        echo -e "${RED}→${NC} Start Redis server: brew services start redis"
        HAS_ERRORS=1
    fi
fi

if [ $HAS_ERRORS -eq 0 ]; then
    echo -e "${GREEN}No obvious issues found.${NC} Check the manual worker test output above."
fi

echo ""
echo "For more details, check logs in: ${LOG_DIR}"
echo ""
