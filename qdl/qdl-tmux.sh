#!/bin/bash
# Mass parallel flashing using tmux
# Each device gets its own pane for monitoring

set -e

# Configuration
QDL_BIN="./qdl"
PROG_FILE="prog_firehose_ddr.elf"
PROGRAM_XML="rawprogram.xml"
PATCH_XML="patch.xml"
LOG_DIR="./flash_logs"
SESSION_NAME="qdl-flash-$(date +%s)"
DRY_RUN=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --prog)
            PROG_FILE="$2"
            shift 2
            ;;
        --program)
            PROGRAM_XML="$2"
            shift 2
            ;;
        --patch)
            PATCH_XML="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create log directory
mkdir -p "$LOG_DIR"

# Get list of connected devices
echo -e "${YELLOW}[*] Enumerating connected devices...${NC}"
devices=$(sudo ${QDL_BIN} list 2>/dev/null | awk '{print $2}' | tail -n +2 || true)

if [ -z "$devices" ]; then
    echo -e "${RED}[!] No devices found!${NC}"
    exit 1
fi

# Convert to array
device_array=($devices)
device_count=${#device_array[@]}

echo -e "${GREEN}[✓] Found $device_count device(s)${NC}"
for dev in "${device_array[@]}"; do
    echo "    - $dev"
done
echo ""

# Verify files exist
for file in "$PROG_FILE" "$PROGRAM_XML" "$PATCH_XML"; do
    if [ ! -f "$file" ]; then
        echo -e "${RED}[!] Error: File not found: $file${NC}"
        exit 1
    fi
done

# Create tmux session with first device in first pane
echo -e "${YELLOW}[*] Creating tmux session: $SESSION_NAME${NC}"
device_index=0
first_device=true

for device in "${device_array[@]}"; do
    log_file="$LOG_DIR/${device}.log"
    
    # Prepare command (removed --debug for speed, added --out-chunk-size optimizations)
    CHUNK_SIZE="16384"  # Optimize for your USB hub (16KB, 32KB, 64KB)
    if [ $DRY_RUN -eq 1 ]; then
        cmd="sudo ${QDL_BIN} -S '$device' --dry-run --out-chunk-size=$CHUNK_SIZE '$PROG_FILE' '$PROGRAM_XML' '$PATCH_XML' 2>&1 | tee '$log_file'"
    else
        cmd="sudo ${QDL_BIN} -S '$device' --out-chunk-size=$CHUNK_SIZE '$PROG_FILE' '$PROGRAM_XML' '$PATCH_XML' 2>&1 | tee '$log_file'"
    fi
    
    if [ "$first_device" = true ]; then
        # Create new session with first device
        tmux new-session -d -s "$SESSION_NAME" -x 240 -y 50
        tmux send-keys -t "$SESSION_NAME" "echo '╔═══════════════════════════════════════════════════════════╗'; echo '║  Device: $device'; echo '║  Log: $log_file'; echo '╚═══════════════════════════════════════════════════════════╝'; echo ''; $cmd" Enter
        echo -e "${GREEN}[✓] Created session and started device: $device${NC}"
        first_device=false
    else
        # Split window horizontally and create new pane for each device
        tmux split-window -h -t "$SESSION_NAME" -c "$PWD"
        tmux send-keys -t "$SESSION_NAME" "echo '╔═══════════════════════════════════════════════════════════╗'; echo '║  Device: $device'; echo '║  Log: $log_file'; echo '╚═══════════════════════════════════════════════════════════╝'; echo ''; $cmd" Enter
        echo -e "${GREEN}[✓] Started flashing on device: $device${NC}"
    fi
    
    sleep 0.3
    device_index=$((device_index + 1))
done

# Balance window layout for better visibility
tmux select-layout -t "$SESSION_NAME" tiled
sleep 0.5

echo ""
echo -e "${GREEN}[✓] All flashing sessions started!${NC}"
echo ""
echo "Tmux Session: $SESSION_NAME"
echo "Attach with: tmux attach -t $SESSION_NAME"
echo ""
echo "Tmux Commands:"
echo "  - Navigate panes: Ctrl-B + Arrow keys"
echo "  - Zoom pane: Ctrl-B + Z"
echo "  - Switch pane: Ctrl-B + O"
echo "  - Kill session: Ctrl-B + X (or 'tmux kill-session -t $SESSION_NAME')"
echo ""
echo "Monitoring:"
echo "  - Watch logs: tail -f $LOG_DIR/*.log"
echo "  - Check status: ls -lh $LOG_DIR/"
echo ""

# Optional: Watch for completion
echo -e "${YELLOW}[*] Waiting for all devices to complete...${NC}"
completed=0
while [ $completed -lt $device_count ]; do
    sleep 5
    completed=$(grep -l "done\|SUCCESS\|error" "$LOG_DIR"/*.log 2>/dev/null | wc -l)
    echo "  Completed: $completed/$device_count"
done

echo ""
echo -e "${GREEN}[✓] All devices finished!${NC}"
echo ""
echo "Summary:"
grep -H "done\|SUCCESS\|FAILED" "$LOG_DIR"/*.log 2>/dev/null || echo "Check logs manually"
