#!/usr/bin/env bash
# create-move-delete-speed.sh
# Usage: ./script.sh [directory] [size_MB]

# Args with defaults
TARGET_DIR="${1:-/tmp}"
SIZE_MB="${2:-50}"
FILENAME="testfile.$$"  # unique filename using PID

# Size in bytes
SIZE_BYTES=$((SIZE_MB * 1024 * 1024))

# Ensure target exists
mkdir -p "$TARGET_DIR" || { echo "Failed to create $TARGET_DIR"; exit 1; }

# Helper function to measure and report speed
measure_speed() {
    local action="$1"
    shift
    local start end duration speed
    start=$(date +%s.%N)
    "$@"
    end=$(date +%s.%N)
    duration=$(echo "$end - $start" | bc -l)
    speed=$(echo "$SIZE_BYTES / $duration" | bc -l)
    printf "%-10s: %.2f seconds | %.2f bytes/sec\n" "$action" "$duration" "$speed"
}

# 1. Create file
measure_speed "Create" dd if=/dev/zero of="$FILENAME" bs=1M count="$SIZE_MB" status=none

# 2. Move file
measure_speed "Move" mv "$FILENAME" "$TARGET_DIR/"

# 3. Remove file
measure_speed "Delete" rm -f "$TARGET_DIR/$FILENAME"
