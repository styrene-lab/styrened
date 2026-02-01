#!/usr/bin/env bash
# cleanup-test-resources.sh - Clean up all styrened test namespaces and resources
#
# Usage:
#   ./cleanup-test-resources.sh           # Interactive cleanup with confirmation
#   ./cleanup-test-resources.sh --force   # Force cleanup without confirmation
#   ./cleanup-test-resources.sh --list    # List resources without deleting

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE=true
            shift
            ;;
        --list|-l)
            LIST_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Clean up styrened test namespaces and resources"
            echo ""
            echo "Options:"
            echo "  --force, -f   Force cleanup without confirmation"
            echo "  --list, -l    List resources without deleting"
            echo "  --help, -h    Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl not found${NC}"
    exit 1
fi

# Get all styrened test namespaces (using label selector)
echo -e "${BLUE}🔍 Searching for styrened test namespaces...${NC}"

NAMESPACES=$(kubectl get namespaces -l styrened-test=true -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")

if [ -z "$NAMESPACES" ]; then
    echo -e "${GREEN}✓ No styrened test namespaces found${NC}"
    exit 0
fi

NS_ARRAY=($NAMESPACES)
NS_COUNT=${#NS_ARRAY[@]}

echo -e "${YELLOW}Found $NS_COUNT test namespace(s):${NC}"
echo ""

# Display namespace details
for ns in "${NS_ARRAY[@]}"; do
    # Get creation timestamp
    CREATED=$(kubectl get namespace "$ns" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null || echo "unknown")

    # Get Helm releases
    RELEASES=$(helm list -n "$ns" -q 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")

    # Get pod count
    POD_COUNT=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | wc -l | tr -d ' ')

    # Get worker and scope labels
    WORKER=$(kubectl get namespace "$ns" -o jsonpath='{.metadata.labels.worker}' 2>/dev/null || echo "unknown")
    SCOPE=$(kubectl get namespace "$ns" -o jsonpath='{.metadata.labels.scope}' 2>/dev/null || echo "unknown")

    echo -e "  ${BLUE}•${NC} $ns"
    echo "    Created: $CREATED"
    echo "    Worker: $WORKER | Scope: $SCOPE"
    echo "    Pods: $POD_COUNT | Helm releases: $RELEASES"
    echo ""
done

# If list-only mode, exit here
if [ "$LIST_ONLY" = true ]; then
    echo -e "${BLUE}ℹ️  List-only mode: no resources deleted${NC}"
    exit 0
fi

# Confirmation prompt (unless --force)
if [ "$FORCE" = false ]; then
    echo -e "${YELLOW}⚠️  This will delete all $NS_COUNT namespace(s) and their resources${NC}"
    read -p "Continue? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}ℹ️  Cleanup cancelled${NC}"
        exit 0
    fi
fi

# Perform cleanup
echo -e "${BLUE}🧹 Starting cleanup...${NC}"
echo ""

CLEANUP_ERRORS=0

for ns in "${NS_ARRAY[@]}"; do
    echo -e "${BLUE}Cleaning up namespace: $ns${NC}"

    # Uninstall Helm releases first
    RELEASES=$(helm list -n "$ns" -q 2>/dev/null || echo "")
    if [ -n "$RELEASES" ]; then
        for release in $RELEASES; do
            echo "  • Uninstalling Helm release: $release"
            if ! helm uninstall "$release" -n "$ns" --wait --timeout 60s 2>/dev/null; then
                echo -e "    ${YELLOW}⚠️  Warning: Failed to uninstall $release${NC}"
                ((CLEANUP_ERRORS++))
            fi
        done
    fi

    # Delete namespace
    echo "  • Deleting namespace: $ns"
    if kubectl delete namespace "$ns" --wait=false 2>/dev/null; then
        echo -e "  ${GREEN}✓ Namespace deletion initiated${NC}"
    else
        echo -e "  ${RED}✗ Failed to delete namespace${NC}"
        ((CLEANUP_ERRORS++))
    fi

    echo ""
done

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $CLEANUP_ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ Cleanup complete - $NS_COUNT namespace(s) deleted${NC}"
else
    echo -e "${YELLOW}⚠️  Cleanup completed with $CLEANUP_ERRORS error(s)${NC}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}Note: Namespace deletion is asynchronous. Use 'kubectl get ns | grep styrene' to check status.${NC}"

exit $CLEANUP_ERRORS
