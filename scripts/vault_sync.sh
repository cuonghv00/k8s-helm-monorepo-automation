#!/bin/bash
# scripts/vault_sync.sh
# ==============================================================================
# Syncs secrets from HashiCorp Vault (KV v2) to K8s Secrets or local .env files.
#
# Usage (K8s - Default): ./vault_sync.sh <vault_path> <secret_name> <namespace>
# Usage (VM):           ./vault_sync.sh vm <vault_path> <env_file>
# ==============================================================================

set -e

# --- Argument Parsing ---
if [ "$1" == "vm" ]; then
    MODE="vm"
    VAULT_PATH="$2"
    ENV_FILE="$3"
    
    if [[ -z "$VAULT_PATH" || -z "$ENV_FILE" ]]; then
        echo "Usage (VM): $0 vm <vault_path> <env_file>"
        exit 1
    fi
else
    MODE="k8s"
    # Support optional 'k8s' keyword or direct path
    if [ "$1" == "k8s" ]; then
        VAULT_PATH="$2"
        SECRET_NAME="$3"
        NAMESPACE="$4"
    else
        VAULT_PATH="$1"
        SECRET_NAME="$2"
        NAMESPACE="$3"
    fi
    
    if [[ -z "$VAULT_PATH" || -z "$SECRET_NAME" || -z "$NAMESPACE" ]]; then
        echo "Usage (K8s): $0 <vault_path> <secret_name> <namespace>"
        exit 1
    fi
fi

# --- Logic: Fetch Secrets ---
fetch_secrets() {
    echo "▶ Fetching from Vault: ${VAULT_PATH}"
    RAW_DATA=$(vault kv get -format=json "${VAULT_PATH}")
    SH_DATA=$(echo "${RAW_DATA}" | jq -r '.data.data')

    if [ "${SH_DATA}" == "null" ] || [ -z "${SH_DATA}" ]; then
        echo "ERROR: No data found at ${VAULT_PATH}."
        exit 1
    fi
    echo "${SH_DATA}"
}

# --- Logic: Deploy to K8s ---
deploy_k8s() {
    local data="$1"
    echo "▶ Syncing to K8s Secret: ${SECRET_NAME} (Namespace: ${NAMESPACE})"
    echo "${data}" | jq -r --arg name "${SECRET_NAME}" --arg ns "${NAMESPACE}" \
        '{apiVersion: "v1", kind: "Secret", type: "Opaque", metadata: {name: $name, namespace: $ns}, stringData: .}' \
        | kubectl apply -f -
    echo "✅ K8s Secret synchronized."
}

# --- Logic: Deploy to VM (.env file) ---
deploy_vm() {
    local data="$1"
    local file="${ENV_FILE}"
    
    if [[ ! -f "$file" ]]; then
        echo "▶ Creating file: ${file}"
        touch "$file"
    fi

    echo "▶ Syncing to file: ${file} (Upsert mode)"

    # Iterate over key-value pairs
    echo "${data}" | jq -r 'to_entries[] | "\(.key) \(.value)"' | while read -r KEY VALUE; do
        if grep -q "^${KEY}=" "$file"; then
            sed -i "s|^${KEY}=.*|${KEY}=${VALUE}|" "$file"
        else
            echo "${KEY}=${VALUE}" >> "$file"
        fi
    done
    echo "✅ VM Environment file updated."
}

# --- Main ---
DATA=$(fetch_secrets)

if [[ "$MODE" == "k8s" ]]; then
    deploy_k8s "$DATA"
else
    deploy_vm "$DATA"
fi
