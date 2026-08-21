#!/bin/bash
#
# Cleanup/Decommission simulated devices from Mender
# Requires: Personal Access Token (PAT) from Mender UI
#

set -e

# Usage
usage() {
    echo "Usage: $0 <action> [options]"
    echo ""
    echo "Actions:"
    echo "  list                  - List all devices"
    echo "  list-pending          - List pending devices"
    echo "  list-accepted         - List accepted devices"
    echo "  list-rejected         - List rejected devices"
    echo "  list-noauth           - List noauth devices"
    echo "  decommission-all      - Decommission ALL devices (dangerous!)"
    echo "  decommission-pending  - Decommission only pending devices"
    echo "  decommission-accepted - Decommission only accepted devices"
    echo "  decommission-rejected - Decommission only rejected devices"
    echo "  decommission-noauth   - Decommission only noauth devices"
    echo "  cleanup-local         - Delete local database only"
    echo ""
    echo "Environment variables:"
    echo "  MENDER_SERVER     - Mender server URL (default: https://hosted.mender.io)"
    echo "  MENDER_PAT        - Personal Access Token (required for API calls)"
    echo ""
    echo "Examples:"
    echo "  export MENDER_PAT='your-personal-access-token'"
    echo "  $0 list-pending"
    echo "  $0 decommission-pending"
    echo "  $0 cleanup-local"
    exit 1
}

# Config
MENDER_SERVER="${MENDER_SERVER:-https://hosted.mender.io}"
ACTION="$1"

if [ -z "$ACTION" ]; then
    usage
fi

# Check PAT for API calls
check_pat() {
    if [ -z "$MENDER_PAT" ]; then
        echo "Error: MENDER_PAT environment variable not set"
        echo ""
        echo "Get your Personal Access Token from:"
        echo "  Mender UI -> Settings -> Access Tokens -> Create new token"
        echo ""
        echo "Then run:"
        echo "  export MENDER_PAT='your-token-here'"
        exit 1
    fi
}

# API call helper
api_call() {
    local method="$1"
    local endpoint="$2"
    local data="$3"

    if [ -n "$data" ]; then
        curl -s -X "$method" \
            -H "Authorization: Bearer $MENDER_PAT" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "${MENDER_SERVER}${endpoint}"
    else
        curl -s -X "$method" \
            -H "Authorization: Bearer $MENDER_PAT" \
            "${MENDER_SERVER}${endpoint}"
    fi
}

# Fetch all devices with pagination (handles any number of devices)
fetch_all_devices() {
    local status="$1"
    python3 -c "
import json, subprocess, sys

server = '${MENDER_SERVER}'
pat = '${MENDER_PAT}'
status = '${status}'
per_page = 500
page = 1
all_devices = []

while True:
    url = f'{server}/api/management/v2/devauth/devices?per_page={per_page}&page={page}'
    if status:
        url += f'&status={status}'

    result = subprocess.run(
        ['curl', '-s', '-X', 'GET', '-H', f'Authorization: Bearer {pat}', url],
        capture_output=True, text=True
    )
    try:
        batch = json.loads(result.stdout)
    except json.JSONDecodeError:
        print('[]')
        sys.exit(0)

    if not isinstance(batch, list):
        print('[]')
        sys.exit(0)

    all_devices.extend(batch)
    print(f'  Fetched page {page} ({len(all_devices)} devices so far)...', file=sys.stderr)

    if len(batch) < per_page:
        break
    page += 1

print(json.dumps(all_devices))
"
}

# List devices
list_devices() {
    local status="$1"

    echo "Fetching devices from $MENDER_SERVER..."
    local response
    response=$(fetch_all_devices "$status")

    # Parse and display
    echo "$response" | python3 -c "
import sys, json
from datetime import datetime

def format_time(ts):
    if not ts:
        return 'N/A'
    try:
        # Parse ISO format and make it readable
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ts

try:
    devices = json.load(sys.stdin)
    if not devices:
        print('No devices found.')
    else:
        print(f'Found {len(devices)} device(s):')
        print()
        for d in devices:
            status = d.get('status', 'unknown')
            device_id = d.get('id', 'unknown')
            identity = d.get('identity_data', {})
            mac = identity.get('mac', 'N/A')
            created = format_time(d.get('created_ts'))
            updated = format_time(d.get('updated_ts'))

            # Get auth sets for more detailed timing
            auth_sets = d.get('auth_sets', [])
            first_request = 'N/A'
            last_request = 'N/A'
            if auth_sets:
                first_request = format_time(auth_sets[0].get('ts'))
                last_request = format_time(auth_sets[-1].get('ts'))

            print(f'  ID: {device_id}')
            print(f'  Status: {status}')
            print(f'  MAC: {mac}')
            print(f'  Created: {created}')
            print(f'  Last update: {updated}')
            print()
except json.JSONDecodeError:
    print('Error parsing response')
    print(sys.stdin.read())
"
}

# Decommission device
decommission_device() {
    local device_id="$1"
    echo "  Decommissioning: $device_id"
    api_call DELETE "/api/management/v2/devauth/devices/${device_id}" > /dev/null
}

# Reject device (for pending)
reject_device() {
    local device_id="$1"
    local auth_set_id="$2"
    echo "  Rejecting: $device_id"
    api_call PUT "/api/management/v2/devauth/devices/${device_id}/auth/${auth_set_id}/status" \
        '{"status":"rejected"}' > /dev/null
}

# Get all device IDs by status
get_device_ids() {
    local status="$1"

    fetch_all_devices "$status" | python3 -c "
import sys, json
try:
    devices = json.load(sys.stdin)
    for d in devices:
        print(d.get('id', ''))
except:
    pass
"
}

# Decommission devices by status
decommission_by_status() {
    local status="$1"
    local label="$2"

    echo "Fetching $label devices..."
    local device_ids
    device_ids=$(get_device_ids "$status")

    if [ -z "$device_ids" ]; then
        echo "No $label devices found."
        return
    fi

    local count
    count=$(echo "$device_ids" | wc -l | tr -d ' ')
    echo "Found $count $label device(s)."
    echo ""
    read -r -p "Are you sure you want to decommission all $count devices? [y/N] " confirm

    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        return
    fi

    echo ""
    echo "Decommissioning devices..."
    echo "$device_ids" | while read -r device_id; do
        if [ -n "$device_id" ]; then
            decommission_device "$device_id"
        fi
    done

    echo ""
    echo "Done. Decommissioned $count device(s)."
}

# Cleanup local database
cleanup_local() {
    echo "Cleaning up local simulator data..."

    local db_files
    local log_files
    db_files=$(find . -name "*.db" -o -name "*.sqlite" 2>/dev/null)
    log_files=$(find . -name "simulator.log" 2>/dev/null)

    if [ -n "$db_files" ]; then
        echo "Found database files:"
        echo "$db_files"
        echo ""
        read -r -p "Delete these files? [y/N] " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            echo "$db_files" | xargs rm -f
            echo "Deleted database files."
        fi
    else
        echo "No database files found."
    fi

    if [ -n "$log_files" ]; then
        echo ""
        echo "Found log files:"
        echo "$log_files"
        echo ""
        read -r -p "Delete these files? [y/N] " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            echo "$log_files" | xargs rm -f
            echo "Deleted log files."
        fi
    fi

    echo ""
    echo "Local cleanup complete."
}

# Main
case "$ACTION" in
    list)
        check_pat
        list_devices ""
        ;;
    list-pending)
        check_pat
        list_devices "pending"
        ;;
    list-accepted)
        check_pat
        list_devices "accepted"
        ;;
    list-rejected)
        check_pat
        list_devices "rejected"
        ;;
    list-noauth)
        check_pat
        list_devices "noauth"
        ;;
    decommission-all)
        check_pat
        decommission_by_status "" "all"
        ;;
    decommission-pending)
        check_pat
        decommission_by_status "pending" "pending"
        ;;
    decommission-accepted)
        check_pat
        decommission_by_status "accepted" "accepted"
        ;;
    decommission-rejected)
        check_pat
        decommission_by_status "rejected" "rejected"
        ;;
    decommission-noauth)
        check_pat
        decommission_by_status "noauth" "noauth"
        ;;
    cleanup-local)
        cleanup_local
        ;;
    *)
        echo "Unknown action: $ACTION"
        usage
        ;;
esac
