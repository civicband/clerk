#!/bin/bash
# install-workers.sh - Create and load LaunchAgent plists for clerk workers
# Reads worker configuration from .env and creates individual LaunchAgent jobs

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory to find template
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/launchd-worker-template.plist"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found in current directory${NC}"
    echo "Please create a .env file with worker configuration."
    echo ""
    echo "Required variables:"
    echo "  FETCH_WORKERS=10"
    echo "  OCR_WORKERS=8"
    echo "  EXTRACTION_WORKERS=2"
    echo "  DEPLOY_WORKERS=2"
    echo "  DEFAULT_OCR_BACKEND=vision"
    echo ""
    exit 1
fi

# Check if template exists
if [ ! -f "${TEMPLATE_FILE}" ]; then
    echo -e "${RED}Error: Template file not found: ${TEMPLATE_FILE}${NC}"
    exit 1
fi

# Load .env file
source .env

# Validate required environment variables
REQUIRED_VARS=("FETCH_WORKERS" "OCR_WORKERS" "EXTRACTION_WORKERS" "DEPLOY_WORKERS")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables in .env:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    exit 1
fi

# Set defaults for optional variables
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
DATABASE_URL="${DATABASE_URL:-sqlite:///civic.db}"
STORAGE_DIR="${STORAGE_DIR:-../sites}"
DEFAULT_OCR_BACKEND="${DEFAULT_OCR_BACKEND:-tesseract}"

# Detect architecture and set PATH for Homebrew + system binaries
# LaunchAgents run with minimal PATH, need to include Homebrew paths for tools like pdfinfo
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    # Apple Silicon: Homebrew is in /opt/homebrew
    PATH_VAR="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
else
    # Intel: Homebrew is in /usr/local
    PATH_VAR="/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
fi

# Get clerk executable path
CLERK_PATH=$(which clerk || echo "")
if [ -z "${CLERK_PATH}" ]; then
    # Try to find clerk in virtual environment
    if [ -d ".venv/bin" ]; then
        CLERK_PATH="$(pwd)/.venv/bin/clerk"
    elif [ -d "venv/bin" ]; then
        CLERK_PATH="$(pwd)/venv/bin/clerk"
    else
        echo -e "${RED}Error: Could not find clerk executable${NC}"
        echo "Make sure clerk is installed and in PATH, or run from project directory with .venv/"
        exit 1
    fi
fi

if [ ! -x "${CLERK_PATH}" ]; then
    echo -e "${RED}Error: clerk executable not found or not executable: ${CLERK_PATH}${NC}"
    exit 1
fi

# Set directories
WORKING_DIR="$(pwd)"
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/.clerk/logs"

# Create directories if they don't exist
mkdir -p "${LAUNCHAGENTS_DIR}"
mkdir -p "${LOG_DIR}"

echo "Installing clerk workers as LaunchAgents..."
echo ""
echo "Configuration:"
echo "  Clerk path: ${CLERK_PATH}"
echo "  Working dir: ${WORKING_DIR}"
echo "  Log dir: ${LOG_DIR}"
echo "  Redis URL: ${REDIS_URL}"
echo "  Database URL: ${DATABASE_URL}"
echo "  Storage dir: ${STORAGE_DIR}"
echo "  OCR backend: ${DEFAULT_OCR_BACKEND}"
echo "  PATH: ${PATH_VAR}"
echo ""
echo "Worker counts:"
echo "  FETCH_WORKERS: ${FETCH_WORKERS}"
echo "  OCR_WORKERS: ${OCR_WORKERS}"
echo "  EXTRACTION_WORKERS: ${EXTRACTION_WORKERS}"
echo "  DEPLOY_WORKERS: ${DEPLOY_WORKERS}"
echo ""

# Counter for total workers
TOTAL_WORKERS=0

# Function to create and load worker plist
create_worker() {
    local worker_type=$1
    local worker_num=$2

    local label="com.civicband.clerk.worker.${worker_type}.${worker_num}"
    local plist_file="${LAUNCHAGENTS_DIR}/${label}.plist"

    # Generate plist from template
    cat "${TEMPLATE_FILE}" | \
        sed "s|{{WORKER_TYPE}}|${worker_type}|g" | \
        sed "s|{{WORKER_NUM}}|${worker_num}|g" | \
        sed "s|{{CLERK_PATH}}|${CLERK_PATH}|g" | \
        sed "s|{{WORKING_DIR}}|${WORKING_DIR}|g" | \
        sed "s|{{REDIS_URL}}|${REDIS_URL}|g" | \
        sed "s|{{DATABASE_URL}}|${DATABASE_URL}|g" | \
        sed "s|{{STORAGE_DIR}}|${STORAGE_DIR}|g" | \
        sed "s|{{DEFAULT_OCR_BACKEND}}|${DEFAULT_OCR_BACKEND}|g" | \
        sed "s|{{PATH}}|${PATH_VAR}|g" | \
        sed "s|{{LOG_DIR}}|${LOG_DIR}|g" \
        > "${plist_file}"

    # Load the plist
    if launchctl load "${plist_file}" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Created and loaded: ${label}"
    else
        # If load failed, try unloading first (in case it was already loaded)
        launchctl unload "${plist_file}" 2>/dev/null || true
        if launchctl load "${plist_file}" 2>/dev/null; then
            echo -e "${YELLOW}✓${NC} Reloaded: ${label}"
        else
            echo -e "${RED}✗${NC} Failed to load: ${label}"
        fi
    fi

    TOTAL_WORKERS=$((TOTAL_WORKERS + 1))
}

# Create workers for each type
echo "Creating worker plists..."
echo ""

# Fetch workers
for ((i=1; i<=FETCH_WORKERS; i++)); do
    create_worker "fetch" "$i"
done

# OCR workers
for ((i=1; i<=OCR_WORKERS; i++)); do
    create_worker "ocr" "$i"
done

# Extraction workers
for ((i=1; i<=EXTRACTION_WORKERS; i++)); do
    create_worker "extraction" "$i"
done

# Deploy workers
for ((i=1; i<=DEPLOY_WORKERS; i++)); do
    create_worker "deploy" "$i"
done

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Summary:"
echo "  Total workers created: ${TOTAL_WORKERS}"
echo "  Fetch: ${FETCH_WORKERS}"
echo "  OCR: ${OCR_WORKERS}"
echo "  Extraction: ${EXTRACTION_WORKERS}"
echo "  Deploy: ${DEPLOY_WORKERS}"
echo ""
echo "Workers are now running as LaunchAgents."
echo "Logs are available in: ${LOG_DIR}"
echo ""
echo "To view worker status:"
echo "  launchctl list | grep com.civicband.clerk.worker"
echo ""
echo "To uninstall workers:"
echo "  ${SCRIPT_DIR}/uninstall-workers.sh"
echo ""
