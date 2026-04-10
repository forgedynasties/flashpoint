#!/usr/bin/env bash
set -euo pipefail

QDL="${QDL_BIN:-/usr/local/bin/qdl}"
STAGGER_SEC=3
EXPECTED_BUILD="AQ3A.250226.002"
BOOT_TIMEOUT=120
EDL_TIMEOUT=60

FAC_FW="${FACTORY_FW_PATH:?Set FACTORY_FW_PATH}"
DBG_FW="${PROD_DEBUG_FW_PATH:?Set PROD_DEBUG_FW_PATH}"

TMPDIR_FLASH=$(mktemp -d)
trap 'rm -rf "$TMPDIR_FLASH"' EXIT

echo "QDL_BIN:            $QDL"
echo "FACTORY_FW_PATH:    $FAC_FW"
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

# Parse the last progress/info JSON line from a qdl log file for a device
get_device_status() {
    local logfile="$1"
    [[ -f "$logfile" ]] || { echo "waiting..."; return; }

    local last_progress last_info task pct msg
    last_progress=$(grep -o '{"event":"progress"[^}]*}' "$logfile" 2>/dev/null | tail -1)
    last_info=$(grep -o '{"event":"info"[^}]*}' "$logfile" 2>/dev/null | tail -1)

    if [[ -n "$last_progress" ]]; then
        task=$(echo "$last_progress" | sed 's/.*"task":"\([^"]*\)".*/\1/')
        pct=$(echo "$last_progress" | sed 's/.*"percent":\([0-9.]*\).*/\1/')
        pct=${pct%.*}  # truncate to int
        # build a bar
        local filled=$(( pct / 5 ))
        local empty=$(( 20 - filled ))
        local bar
        bar=$(printf '%0.s#' $(seq 1 $filled 2>/dev/null) )
        bar+=$(printf '%0.s-' $(seq 1 $empty 2>/dev/null) )
        echo "[${bar}] ${pct}% ${task}"
    elif [[ -n "$last_info" ]]; then
        msg=$(echo "$last_info" | sed 's/.*"message":"\([^"]*\)".*/\1/')
        echo "$msg"
    else
        echo "starting..."
    fi
}

draw_status() {
    local serials=("$@")
    local n=${#serials[@]}
    # move cursor up n+1 lines and redraw
    for (( i = 0; i < n + 1; i++ )); do
        echo -ne "\033[A\033[2K"
    done
    echo "  Devices:"
    for i in "${!serials[@]}"; do
        local serial="${serials[$i]}"
        local pidfile="$TMPDIR_FLASH/${serial}.pid"
        local logfile="$TMPDIR_FLASH/${serial}.log"
        local status marker

        status=$(get_device_status "$logfile")

        if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            marker="~"  # running
        elif [[ -f "$pidfile" ]]; then
            wait "$(cat "$pidfile")" 2>/dev/null && marker="+" || marker="X"  # done or failed
        else
            marker="."  # not started
        fi

        printf "  %s %-12s %s\n" "$marker" "$serial" "$status"
    done
}

flash_all() {
    local fw_dir="$1" stage="$2"
    find_fw "$fw_dir"
    echo ""
    echo "=== Stage $stage: $fw_dir ==="
    echo "  prog:  $(basename "$PROG")"
    echo "  raw:   $(basename "$RAW")"
    echo "  patch: $(basename "$PATCH")"
    echo ""

    local serials=("${SERIALS[@]}")
    local n=${#serials[@]}

    # clean up previous log/pid files
    for s in "${serials[@]}"; do
        rm -f "$TMPDIR_FLASH/${s}.log" "$TMPDIR_FLASH/${s}.pid"
    done

    # print blank lines for status area
    echo "  Devices:"
    for s in "${serials[@]}"; do
        printf "  . %-12s waiting...\n" "$s"
    done

    cd "$fw_dir"

    # launch all devices in parallel with small stagger
    for i in "${!serials[@]}"; do
        local serial="${serials[$i]}"
        "$QDL" --json -S "$serial" -s emmc \
            "$(basename "$PROG")" "$(basename "$RAW")" "$(basename "$PATCH")" \
            -u 1048576 > "$TMPDIR_FLASH/${serial}.log" 2>&1 &
        echo $! > "$TMPDIR_FLASH/${serial}.pid"
    done

    # poll until all done
    while true; do
        local running=0
        for s in "${serials[@]}"; do
            local pidfile="$TMPDIR_FLASH/${s}.pid"
            if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
                running=$((running + 1))
            fi
        done
        draw_status "${serials[@]}"
        if (( running == 0 )); then
            break
        fi
        sleep 1
    done

    # check results
    local failed=0
    for s in "${serials[@]}"; do
        if ! wait "$(cat "$TMPDIR_FLASH/${s}.pid")" 2>/dev/null; then
            failed=1
        fi
    done
    echo ""
    if (( failed )); then
        echo "Stage $stage: SOME DEVICES FAILED"
        exit 1
    fi
    echo "Stage $stage: ALL OK"
}

wait_adb() {
    echo ""
    echo "=== Waiting for ${#SERIALS[@]} device(s) in ADB (timeout ${BOOT_TIMEOUT}s) ==="
    local elapsed=0
    while (( elapsed < BOOT_TIMEOUT )); do
        local count
        count=$(adb devices -l 2>/dev/null | grep -c 'transport_id' || true)
        echo -ne "\r  $count / ${#SERIALS[@]} in ADB (${elapsed}s)   "
        if (( count >= ${#SERIALS[@]} )); then
            echo ""
            echo "  all devices in ADB"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo ""
    echo "  TIMEOUT waiting for ADB"
    exit 1
}

check_build() {
    echo ""
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
    echo ""
    echo "=== Rebooting ${#REBOOT_TIDS[@]} device(s) to EDL ==="
    for tid in "${REBOOT_TIDS[@]}"; do
        adb -t "$tid" reboot edl &
    done
    wait
    sleep 3
    local elapsed=3
    while (( elapsed < EDL_TIMEOUT )); do
        mapfile -t SERIALS < <(get_serials)
        echo -ne "\r  ${#SERIALS[@]} / ${#REBOOT_TIDS[@]} in EDL (${elapsed}s)   "
        if (( ${#SERIALS[@]} >= ${#REBOOT_TIDS[@]} )); then
            echo ""
            echo "  all devices in EDL"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo ""
    echo "  TIMEOUT waiting for EDL"
    exit 1
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo "Scanning for EDL devices... (press any key to proceed)"
while true; do
    mapfile -t SERIALS < <(get_serials)
    echo -ne "\r  ${#SERIALS[@]} EDL device(s) found: ${SERIALS[*]:-none}  "
    read -t 2 -n 1 key 2>/dev/null && break || true
done
echo ""
if [[ ${#SERIALS[@]} -eq 0 ]]; then
    echo "No devices — aborting."
    exit 1
fi

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

echo ""
echo "=== ALL DONE ==="
