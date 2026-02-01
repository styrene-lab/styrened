#!/bin/bash
# Download test metrics from GitHub Actions artifacts
#
# Usage:
#   ./scripts/download_metrics.sh [workflow] [run-id]
#
# Examples:
#   # Download from latest nightly build
#   ./scripts/download_metrics.sh nightly-build latest
#
#   # Download from specific run ID
#   ./scripts/download_metrics.sh nightly-build 1234567890
#
#   # Download all metrics artifacts from latest release
#   ./scripts/download_metrics.sh release latest
#
# Requirements:
#   - gh CLI installed and authenticated (https://cli.github.com/)
#
# Output:
#   Downloads artifacts to ./metrics-analysis/{workflow}-{run-id}/

set -euo pipefail

# Default arguments
WORKFLOW="${1:-nightly-build}"
RUN_ID="${2:-latest}"
OUTPUT_DIR="./metrics-analysis"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Downloading metrics from GitHub Actions..."
echo "  Workflow: $WORKFLOW"
echo "  Run ID: $RUN_ID"
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: gh CLI not found${NC}"
    echo "Install from: https://cli.github.com/"
    exit 1
fi

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo -e "${RED}Error: gh CLI not authenticated${NC}"
    echo "Run: gh auth login"
    exit 1
fi

# Get actual run ID if "latest" specified
if [ "$RUN_ID" = "latest" ]; then
    echo "Fetching latest run ID for workflow '$WORKFLOW'..."
    RUN_ID=$(gh run list --workflow "$WORKFLOW.yml" --limit 1 --json databaseId --jq '.[0].databaseId')

    if [ -z "$RUN_ID" ]; then
        echo -e "${RED}Error: Could not find latest run for workflow '$WORKFLOW'${NC}"
        exit 1
    fi

    echo -e "${GREEN}Found run ID: $RUN_ID${NC}"
fi

# Create output directory
RUN_OUTPUT_DIR="$OUTPUT_DIR/$WORKFLOW-$RUN_ID"
mkdir -p "$RUN_OUTPUT_DIR"

echo ""
echo "Downloading artifacts to: $RUN_OUTPUT_DIR"
echo ""

# Download all artifacts matching "*metrics*"
# The -n flag filters artifact names, -D specifies destination
if gh run download "$RUN_ID" -n "*metrics*" -D "$RUN_OUTPUT_DIR" 2>/dev/null; then
    echo -e "${GREEN}✓ Download complete${NC}"
    echo ""

    # List downloaded files
    echo "Downloaded metrics:"
    find "$RUN_OUTPUT_DIR" -name "summary.json" | while read -r summary; do
        run_dir=$(dirname "$summary")
        test_name=$(jq -r '.metadata.test_name' "$summary" 2>/dev/null || echo "unknown")
        duration=$(jq -r '.total_duration_seconds' "$summary" 2>/dev/null || echo "0")

        # Convert duration to hours/minutes
        hours=$((duration / 3600))
        minutes=$(((duration % 3600) / 60))

        if [ "$hours" -gt 0 ]; then
            duration_str="${hours}h ${minutes}m"
        else
            duration_str="${minutes}m"
        fi

        echo "  - $test_name ($duration_str)"
    done

    echo ""
    echo "Analysis commands:"
    echo "  # Analyze single test"
    echo "  python scripts/analyze_metrics.py $RUN_OUTPUT_DIR/<test-dir>/"
    echo ""
    echo "  # Analyze all tests"
    echo "  python scripts/analyze_metrics.py $RUN_OUTPUT_DIR/ --all"

else
    echo -e "${YELLOW}Warning: No metrics artifacts found for run $RUN_ID${NC}"
    echo "This could mean:"
    echo "  - Workflow run did not include metrics collection"
    echo "  - Artifacts have expired (90-day retention)"
    echo "  - Run is still in progress"

    # Show available artifacts for this run
    echo ""
    echo "Available artifacts for this run:"
    gh run view "$RUN_ID" --json artifacts --jq '.artifacts[] | "  - \(.name)"' 2>/dev/null || echo "  (could not list artifacts)"

    exit 1
fi
