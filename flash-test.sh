#!/usr/bin/env bash
set -euo pipefail

QDL="${QDL_BIN:-/usr/local/bin/qdl}"
STAGGER_SEC=3
EXPECTED_BUILD="AQ3A.250226.002"
BOOT_TIMEOUT=120
EDL_TIMEOUT=60

FAC_FW="${FACTORY_FW_PATH:?Set FACTORY_FW_PATH}"
DBG_FW="${PROD_DEBUG_FW_PATH:?Set PROD_DEBUG_FW_PATH}"

echo "QDL_BIN:          $QDL"
echo "FACTORY_FW_PATH:  $FAC_FW"
echo "PROD_DEBUG_FW_PATH: $DBG_FW"
echo ""

find_fw() {
    local dir="$1"
    PROG=$(find "$dir" -maxdepth 1 -name '*prog*.elf' | head -1)
    RAW=$(find "$dir" -maxdepth 1 -name '*rawprogram*.xml' | head -1)
    PATCH=$(find "$dir" -maxdepth 1 -name '*patch*.xml' | head -1)
    if [[ -z "$PROG" || -z "$RAW" || -z "$PATCH" ]]; then
        echo "ERROR: missing firmware files in $dir"
        exit 1
    fi
}

get_serials() {
    "$QDL" list 2>/dev/null | awk '{print $2}'
}

flash_all() {
    local fw_dir="$1" stage="$2"
    find_fw "$fw_dir"
    echo "=== Stage $stage: $fw_dir ==="
    echo "  prog:  $(basename "$PROG")"
    echo "  raw:   $(basename "$RAW")"
    echo "  patch: $(basename "$PATCH")"

    local pids=() serials=("${SERIALS[@]}")
    cd "$fw_dir"
    for i in "${!serials[@]}"; do
        if (( i > 0 )); then
            echo "  stagger ${STAGGER_SEC}s..."
            sleep "$STAGGER_SEC"
        fi
        echo "  flashing ${serials[$i]}"
        "$QDL" --json -S "${serials[$i]}" -s emmc \
            "$(basename "$PROG")" "$(basename "$RAW")" "$(basename "$PATCH")" \
            -u 1048576 &
        pids+=($!)
    done

    local failed=0
    for i in "${!pids[@]}"; do
        if wait "${pids[$i]}"; then
            echo "  ${serials[$i]}: OK"
        else
            echo "  ${serials[$i]}: FAILED"
            failed=1
        fi
    done
    if (( failed )); then
        echo "Stage $stage failed."
        exit 1
    fi
}

wait_adb() {
    echo "=== Waiting for ${#SERIALS[@]} device(s) in ADB (timeout ${BOOT_TIMEOUT}s) ==="
    local elapsed=0
    while (( elapsed < BOOT_TIMEOUT )); do
        local count
        count=$(adb devices -l 2>/dev/null | grep -c 'transport_id')
        echo "  $count / ${#SERIALS[@]} in ADB (${elapsed}s)"
        if (( count >= ${#SERIALS[@]} )); then
            echo "  all devices in ADB"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo "  TIMEOUT waiting for ADB"
    exit 1
}

check_build() {
    echo "=== Checking build IDs ==="
    local tids
    mapfile -t tids < <(adb devices -l 2>/dev/null | awk '/transport_id/{for(i=1;i<=NF;i++) if($i ~ /^transport_id:/) print substr($i,14)}')
    REBOOT_TIDS=()
    for tid in "${tids[@]}"; do
        local bid
        bid=$(adb -t "$tid" shell getprop ro.build.display.id 2>/dev/null | tr -d '\r')
        if [[ "$bid" == "$EXPECTED_BUILD" ]]; then
            echo "  transport=$tid build=$bid OK"
            REBOOT_TIDS+=("$tid")
        else
            echo "  transport=$tid build=$bid MISMATCH"
        fi
    done
    if (( ${#REBOOT_TIDS[@]} < ${#SERIALS[@]} )); then
        echo "  not enough devices with correct build"
        exit 1
    fi
}

reboot_to_edl() {
    echo "=== Rebooting ${#REBOOT_TIDS[@]} device(s) to EDL ==="
    for tid in "${REBOOT_TIDS[@]}"; do
        adb -t "$tid" reboot edl &
    done
    wait
    echo "  waiting for devices to re-enter EDL (timeout ${EDL_TIMEOUT}s)..."
    sleep 3
    local elapsed=3
    while (( elapsed < EDL_TIMEOUT )); do
        mapfile -t SERIALS < <(get_serials)
        echo "  ${#SERIALS[@]} / ${#REBOOT_TIDS[@]} in EDL (${elapsed}s)"
        if (( ${#SERIALS[@]} >= ${#REBOOT_TIDS[@]} )); then
            echo "  all devices in EDL"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo "  TIMEOUT waiting for EDL"
    exit 1
}

# ── Main ──────────────────────────────────────────────────────────────────────

mapfile -t SERIALS < <(get_serials)
if [[ ${#SERIALS[@]} -eq 0 ]]; then
    echo "No EDL devices found."
    exit 1
fi
echo "Found ${#SERIALS[@]} device(s): ${SERIALS[*]}"

# Stage 1: factory firmware
flash_all "$FAC_FW" 1

# Wait for ADB
wait_adb

# Verify build
check_build

# Reboot to EDL for stage 3
reboot_to_edl

# Stage 3: debug firmware
flash_all "$DBG_FW" 3

echo "=== DONE ==="
