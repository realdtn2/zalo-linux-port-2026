#!/bin/bash

set -e

# --- CONFIG ---
ELECTRON_VERSION="v22.3.27"
ELECTRON_DIR="$HOME/.local/electron-$ELECTRON_VERSION"
ELECTRON_BIN="$ELECTRON_DIR/electron"
DOWNLOAD_URL="https://github.com/electron/electron/releases/download/$ELECTRON_VERSION/electron-$ELECTRON_VERSION-linux-x64.zip"

# --- DOWNLOAD IF NOT EXISTS ---
if [ ! -f "$ELECTRON_BIN" ]; then
    echo "[*] Electron $ELECTRON_VERSION not found. Downloading..."

    TMP_ZIP="/tmp/electron-$ELECTRON_VERSION.zip"

    wget -O "$TMP_ZIP" "$DOWNLOAD_URL"

    mkdir -p "$ELECTRON_DIR"
    unzip -q "$TMP_ZIP" -d "$ELECTRON_DIR"

    # Move contents up if needed (zip has subfolder)
    if [ -d "$ELECTRON_DIR/electron-$ELECTRON_VERSION-linux-x64" ]; then
        mv "$ELECTRON_DIR"/electron-$ELECTRON_VERSION-linux-x64/* "$ELECTRON_DIR"
        rmdir "$ELECTRON_DIR/electron-$ELECTRON_VERSION-linux-x64"
    fi

    rm "$TMP_ZIP"

    chmod +x "$ELECTRON_BIN"

    echo "[*] Electron downloaded."
fi

# --- RUN APP ---
echo "[*] Launching with Electron $ELECTRON_VERSION..."

ELECTRON_ENABLE_LOGGING=1 "$ELECTRON_BIN" .
