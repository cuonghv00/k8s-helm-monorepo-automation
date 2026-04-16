#!/bin/bash
# scripts/deploy.sh
# ==============================================================================
# Automates the Helm Monorepo deployment pipeline:
# 1. Generates Helm charts for a specific project and environment.
# 2. Checks for Git changes in the generated charts.
# 3. Commits and pushes changes back to the repository (Write-back GitOps).
#
# Usage: ./deploy.sh --project <name> --env <dev|stg|prod> [--dry-run]
# ==============================================================================

set -e

# Default values
PROJECT=""
ENV="dev"
DRY_RUN=false
IMAGE_TAG=""
GIT_USER="bot-generator"
GIT_EMAIL="bot@devops.vn"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --project) PROJECT="$2"; shift ;;
        --env) ENV="$2"; shift ;;
        --image-tag) IMAGE_TAG="$2"; shift ;;
        --dry-run) DRY_RUN=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$PROJECT" ]; then
    echo "ERROR: --project is required."
    exit 1
fi

echo "=== Deployment Orchestrator ==="
echo "Project : ${PROJECT}"
echo "Env     : ${ENV}"
echo "Dry Run : ${DRY_RUN}"
echo "-------------------------------"

# 1. Run the Generator
echo "▶ Running Generator..."
GEN_CMD="python3 scripts/generator.py --project ${PROJECT} --env ${ENV}"
if [ ! -z "$IMAGE_TAG" ]; then
    GEN_CMD="${GEN_CMD} --image-tag ${IMAGE_TAG}"
fi
$GEN_CMD

# 2. Check for Git Changes
TARGET_DIR="projects/${PROJECT}/charts"
if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory ${TARGET_DIR} does not exist after generation."
    exit 1
fi

CHANGES=$(git status --porcelain "$TARGET_DIR")

if [ -z "$CHANGES" ]; then
    echo "✅ No changes detected in ${TARGET_DIR}. Skip commit."
    exit 0
fi

echo "▶ Changes detected in ${TARGET_DIR}:"
echo "${CHANGES}"

# 3. Commit and Push (Write-back)
if [ "$DRY_RUN" = true ]; then
    echo "⚠️  Dry-run mode: Skipping Git commit and push."
    exit 0
fi

echo "▶ Committing changes..."
# Configure local bot user for this commit
git config user.name "${GIT_USER}"
git config user.email "${GIT_EMAIL}"

git add "$TARGET_DIR"
# [skip ci] prevents the CI from entering an infinite loop when this script pushes back
git commit -m "chore(ops): update generated charts for ${PROJECT} (${ENV}) [skip ci]"

echo "▶ Pushing changes to origin (with retry logic)..."
MAX_RETRIES=5
RETRY_COUNT=0
SUCCESS=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    # Pull latest changes and rebase our commit on top to avoid conflicts
    # Since each app lives in its own directory, rebase conflicts are unlikely.
    if git pull --rebase origin HEAD; then
        if git push origin HEAD; then
            SUCCESS=true
            break
        fi
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "⚠️  Push failed (likely concurrent update). Retrying in 5s... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 5
done

if [ "$SUCCESS" = true ]; then
    echo "✅ Deployment manifests successfully updated in Git."
    echo "   ArgoCD will now detect and sync these changes."
else
    echo "❌ ERROR: Failed to push changes after $MAX_RETRIES attempts."
    exit 1
fi
