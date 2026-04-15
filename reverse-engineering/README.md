## Reverse engineering notes (Zalo native addons)

This folder contains **offline reverse-engineering artifacts** used to port the macOS Zalo Electron native addon behavior to Linux.

### What’s in here

- `darwin/`
  - `db-cross-v4-native.disasm.txt`: full `llvm-objdump` disassembly dump of the macOS Mach-O addon, used for branch-by-branch reconstruction.
  - `machofile/*.json`: `machofile` JSON reports (symbols/imports/exports/etc.) for Darwin universal/x64/arm64 slices.
- `old-linux/`
  - `db-cross-v4-native.old.node`: older Linux addon binary kept for comparison.
- `tools/`
  - small scripts to validate decrypted DBs and debug `parseBinNet`.

### How to regenerate (Linux)

- **Disassembly dump (Darwin addon)**:

```bash
llvm-objdump --macho --demangle --disassemble \
  "native/nativelibs/db-cross-v4/prebuilt/darwin/electron/db-cross-v4-native.node" \
  > "reverse-engineering/darwin/db-cross-v4-native.disasm.txt"
```

- **Mach-O structure/symbol report (Darwin addon) using `machofile`**:
  - We install `machofile` into a workspace-local target directory to avoid system Python restrictions:

```bash
python3 -m pip install --break-system-packages --target "reverse-engineering/vendor/pydeps" machofile
PYTHONPATH="reverse-engineering/vendor/pydeps" \
  python3 "reverse-engineering/vendor/pydeps/machofile/machofile.py" -j -a \
  -f "native/nativelibs/db-cross-v4/prebuilt/darwin/electron/db-cross-v4-native.node" \
  > "reverse-engineering/darwin/machofile/darwin-universal.json"
```

### Where the Linux implementation lives

- **Source generator**: `generate-addon.py` (embeds C++ source and rebuilds the Linux `.node`)
- **Built binary**: `native/nativelibs/db-cross-v4/prebuilt/linux/electron/x64/db-cross-v4-native.node`

