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
    # Use -format=json and jq for reliable parsing
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
    # Use stringData for automatic base64 encoding by kubectl
    echo "${data}" | jq -r --arg name "${SECRET_NAME}" --arg ns "${NAMESPACE}" \
        '{apiVersion: "v1", kind: "Secret", type: "Opaque", metadata: {name: $name, namespace: $ns}, stringData: .}' \
        | kubectl apply -f -
    echo "✅ K8s Secret synchronized."
}

# --- Logic: Deploy to VM (.env file) ---
# Hardened version using Python to safely handle special characters (No more sed injection)
deploy_vm() {
    local data="$1"
    local file="${ENV_FILE}"
    
    if [[ ! -f "$file" ]]; then
        echo "▶ Creating file: ${file}"
        touch "$file"
    fi

    echo "▶ Syncing to file: ${file} (Robust Upsert via Python)"

    # Pass the entire JSON data to Python for processing
    echo "${data}" | python3 -c "
import sys, json, os

env_file = '$file'
try:
    vault_data = json.load(sys.stdin)
except Exception as e:
    print(f'ERROR: Invalid JSON data: {e}')
    sys.exit(1)

# Read existing file
lines = []
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        lines = f.readlines()

new_lines = []
processed_keys = set()

# Update existing keys
for line in lines:
    clean_line = line.strip()
    if clean_line and not clean_line.startswith('#') and '=' in clean_line:
        key = clean_line.split('=', 1)[0].strip()
        if key in vault_data:
            new_lines.append(f'{key}={vault_data[key]}\n')
            processed_keys.add(key)
            continue
    new_lines.append(line)

# Add new keys
for key, value in vault_data.items():
    if key not in processed_keys:
        new_lines.append(f'{key}={value}\n')

with open(env_file, 'w') as f:
    f.writelines(new_lines)
"
    # Ensure strict permissions for secret file
    chmod 600 "$file"
    echo "✅ VM Environment file updated (Permissions: 600)."
}

# --- Main ---
DATA=$(fetch_secrets)

if [[ "$MODE" == "k8s" ]]; then
    deploy_k8s "$DATA"
else
    deploy_vm "$DATA"
fi
