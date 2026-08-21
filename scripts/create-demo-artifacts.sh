#!/bin/bash
#
# Create demo artifacts for Mender Fleet Simulator
# Requires: mender-artifact tool (https://docs.mender.io/downloads)
#

set -e

# Usage
usage() {
    echo "Usage: $0 <industry> [output_dir]"
    echo ""
    echo "Industries:"
    echo "  automotive      - tcu-4g-lte"
    echo "  smart_buildings - bms-controller-hvac"
    echo "  medical         - patient-monitor-icu"
    echo "  industrial_iot  - plc-gateway-modbus"
    echo "  retail          - pos-terminal-emv"
    echo "  ev_charging     - ev-charger-ocpp-2.0"
    echo "  off_highway     - telematics-gateway-j1939"
    echo "  all             - All industries"
    echo ""
    echo "Examples:"
    echo "  $0 smart_buildings"
    echo "  $0 automotive ./my-artifacts"
    echo "  $0 all ./artifacts"
    exit 1
}

# Check arguments
if [ -z "$1" ]; then
    usage
fi

INDUSTRY="$1"
OUTPUT_DIR="${2:-./artifacts}"
mkdir -p "$OUTPUT_DIR"

# Map industry to device type (bash 3.2 compatible)
get_device_type() {
    case "$1" in
        automotive) echo "tcu-4g-lte" ;;
        smart_buildings) echo "bms-controller-hvac" ;;
        medical) echo "patient-monitor-icu" ;;
        industrial_iot) echo "plc-gateway-modbus" ;;
        retail) echo "pos-terminal-emv" ;;
        ev_charging) echo "ev-charger-ocpp-2.0" ;;
        off_highway) echo "telematics-gateway-j1939" ;;
        *) echo "" ;;
    esac
}

# All device types
ALL_DEVICE_TYPES="tcu-4g-lte bms-controller-hvac patient-monitor-icu plc-gateway-modbus pos-terminal-emv ev-charger-ocpp-2.0 telematics-gateway-j1939"

# Versions to generate
VERSIONS="v1.0.0 v1.1.0 v1.2.0 v2.0.0"

# Check if mender-artifact is installed
if ! command -v mender-artifact &> /dev/null; then
    echo "Error: mender-artifact not found"
    echo ""
    echo "Install it from: https://docs.mender.io/downloads"
    echo ""
    echo "macOS:   brew install mender-artifact"
    echo "Linux:   Download from Mender website"
    exit 1
fi

# Get device types to process
if [ "$INDUSTRY" = "all" ]; then
    DEVICE_TYPES="$ALL_DEVICE_TYPES"
else
    DEVICE_TYPE=$(get_device_type "$INDUSTRY")
    if [ -z "$DEVICE_TYPE" ]; then
        echo "Error: Unknown industry '$INDUSTRY'"
        echo ""
        usage
    fi
    DEVICE_TYPES="$DEVICE_TYPE"
fi

echo "Creating demo artifacts in: $OUTPUT_DIR"
echo ""

# Create a dummy payload file
PAYLOAD_FILE=$(mktemp)
echo "Demo firmware payload - $(date)" > "$PAYLOAD_FILE"
dd if=/dev/urandom bs=1024 count=100 >> "$PAYLOAD_FILE" 2>/dev/null  # Add ~100KB

# Generate artifacts
for DEVICE_TYPE in $DEVICE_TYPES; do
    echo "=== Device Type: $DEVICE_TYPE ==="

    for VERSION in $VERSIONS; do
        ARTIFACT_NAME="${DEVICE_TYPE}-${VERSION}"
        OUTPUT_FILE="${OUTPUT_DIR}/${ARTIFACT_NAME}.mender"

        echo "  Creating: $ARTIFACT_NAME"

        mender-artifact write rootfs-image \
            --device-type "$DEVICE_TYPE" \
            --artifact-name "$ARTIFACT_NAME" \
            --file "$PAYLOAD_FILE" \
            --output-path "$OUTPUT_FILE" \
            2>/dev/null

        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo "    -> $OUTPUT_FILE ($SIZE)"
    done
    echo ""
done

# Cleanup
rm -f "$PAYLOAD_FILE"

# Summary
TOTAL=$(find "$OUTPUT_DIR" -name "*.mender" | wc -l | tr -d ' ')
FIRST_DEVICE=$(echo "$DEVICE_TYPES" | awk '{print $1}')
echo "=== Summary ==="
echo "Created artifacts in $OUTPUT_DIR"
echo ""
echo "To upload to Mender:"
echo "  mender-cli artifacts upload $OUTPUT_DIR/${FIRST_DEVICE}*.mender"
