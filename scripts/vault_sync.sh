#!/bin/bash
# scripts/vault_sync.sh
# ==============================================================================
# Syncs secrets from HashiCorp Vault (KV v2) to a Kubernetes Secret.
# Usage: ./vault_sync.sh <team> <project> <env> <namespace>
#
# Requirements:
#   - vault CLI (authenticated)
#   - jq
#   - kubectl (context set to target cluster)
# ==============================================================================

set -e

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <team> <project> <env> <namespace>"
    exit 1
fi

TEAM=$1
PROJECT=$2
ENV=$3
NAMESPACE=$4

# Configurable Vault mount point (defaults to 'secret')
VAULT_MOUNT=${VAULT_MOUNT:-secret}
SECRET_NAME="${PROJECT}-secret"
VAULT_PATH="${VAULT_MOUNT}/data/${TEAM}/${PROJECT}/${ENV}"

echo "--- Vault Syncing ---"
echo "Project   : ${PROJECT}"
echo "Namespace : ${NAMESPACE}"
echo "Vault Path: ${VAULT_PATH}"

# 1. Fetch data from Vault (KV v2)
# The data is nested under .data.data in KV v2 format when fetching with -format=json
RAW_DATA=$(vault kv get -format=json "${VAULT_PATH}")

# 2. Extract the actual secret data and format it into a K8s Secret manifest
# jq --raw-output is used to make sure we don't have extra quotes
SH_DATA=$(echo "${RAW_DATA}" | jq -r '.data.data')

if [ "${SH_DATA}" == "null" ] || [ -z "${SH_DATA}" ]; then
    echo "ERROR: No data found at ${VAULT_PATH} or failed to parse JSON."
    exit 1
fi

# 3. Create/Update Secret using kubectl apply
# We pipe the JSON directly to kubectl (it supports JSON manifests)
# Note: We need to set the metadata correctly before applying
echo "${SH_DATA}" | jq -r --arg name "${SECRET_NAME}" --arg ns "${NAMESPACE}" \
    '{apiVersion: "v1", kind: "Secret", type: "Opaque", metadata: {name: $name, namespace: $ns}, stringData: .}' \
    | kubectl apply -f -

echo "✅ Secret '${SECRET_NAME}' successfully synced to namespace '${NAMESPACE}'."
