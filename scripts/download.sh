#!/bin/bash
set -e

URL="https://s3.jbecker.dev/data.tar.zst"
OUTPUT_FILE="data.tar.zst"
DATA_DIR="data"

# Check if data directory already exists
if [ -d "$DATA_DIR" ]; then
    echo "Data directory already exists, skipping download."
    exit 0
fi

# Download file using best available tool.
# This server does NOT support HTTP Range, so resume is not possible.
# Use curl by default. Set USE_ARIA2=1 to use aria2c; set ARIA2_SINGLE=1 to use
# one connection (avoids TLS handshake errors on some networks).
download() {
    if [ -n "${USE_ARIA2:-}" ] && command -v aria2c &> /dev/null; then
        if [ -n "${ARIA2_SINGLE:-}" ]; then
            echo "Downloading with aria2c (single connection, USE_ARIA2=1 ARIA2_SINGLE=1)..."
            aria2c -x 1 -s 1 -o "$OUTPUT_FILE" "$URL"
        else
            echo "Downloading with aria2c (USE_ARIA2=1)..."
            aria2c -x 16 -s 16 -o "$OUTPUT_FILE" "$URL"
        fi
    elif command -v curl &> /dev/null; then
        if [ -s "$OUTPUT_FILE" ]; then
            echo "Resuming download with curl (partial file found)..."
            curl -L -C - -o "$OUTPUT_FILE" "$URL"
        else
            echo "Downloading with curl..."
            curl -L -o "$OUTPUT_FILE" "$URL"
        fi
    elif command -v aria2c &> /dev/null; then
        if [ -n "${ARIA2_SINGLE:-}" ]; then
            echo "Using aria2c (single connection)..."
            aria2c -x 1 -s 1 -o "$OUTPUT_FILE" "$URL"
        else
            echo "curl not found, using aria2c..."
            aria2c -x 16 -s 16 -o "$OUTPUT_FILE" "$URL"
        fi
    elif command -v wget &> /dev/null; then
        echo "Using wget..."
        wget -O "$OUTPUT_FILE" "$URL"
    else
        echo "Error: No download tool available (curl, aria2c, or wget required)."
        exit 1
    fi
}

# Extract the archive
extract() {
    if ! command -v zstd &> /dev/null; then
        echo "Error: zstd is required but not installed."
        echo "Run 'make setup' or install zstd manually."
        exit 1
    fi

    echo "Extracting $OUTPUT_FILE..."
    zstd -d "$OUTPUT_FILE" --stdout | tar -xf -
    echo "Extraction complete."
}

# Cleanup downloaded archive
cleanup() {
    if [ -f "$OUTPUT_FILE" ]; then
        echo "Cleaning up..."
        rm "$OUTPUT_FILE"
    fi
}

# Main
download
extract
cleanup

echo "Data directory ready."
