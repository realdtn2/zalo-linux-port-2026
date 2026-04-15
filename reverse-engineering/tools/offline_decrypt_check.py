#!/usr/bin/env python3
"""
Offline validator for Zalo *.db.crypt decrypt output.

It uses the installed Linux addon (`native/nativelibs/db-cross-v4/dist/binding.js`)
to decrypt a single *.db.crypt into a temp folder, then validates extracted *.db
files by:
  - SQLite file header check
  - PRAGMA integrity_check (read-only)

Usage:
  python tools/offline_decrypt_check.py /path/to/file.db.crypt <privateKey> [--out /tmp/outdir]
"""

from __future__ import annotations

import argparse
import os
import tempfile
import sqlite3
import subprocess
import sys
from pathlib import Path

SQLITE_HDR = b"SQLite format 3\x00"


def is_sqlite_header(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_HDR
    except OSError:
        return False


def sqlite_integrity_ok(path: Path) -> tuple[bool, str]:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            row = con.execute("PRAGMA integrity_check;").fetchone()
            msg = (row[0] if row else "") or ""
            return (msg.lower() == "ok"), msg
        finally:
            con.close()
    except Exception as e:
        return False, f"open/integrity_check failed: {e}"


NODE_RUNNER = r"""
const binding = require(process.argv[1]); // binding.js absolute path
const input = process.argv[2];
const outdir = process.argv[3];
const key = process.argv[4];
let files = 0;
const res = binding.decompressAndDecryptDb_V2(input, outdir, key, () => { files++; });
console.error("[OFFLINE] result=", res && res.result, "inner=", res && (res.inner_error || res.error_message), "filesCb=", files);
process.exit((res && res.result) ? 2 : 0);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("crypt", help="Path to *.db.crypt")
    ap.add_argument("key", help="privateKey string from logs")
    ap.add_argument("--out", help="Output directory (default: <crypt>_tmp_offline)")
    ap.add_argument("--node", help="Path to a specific *.node to require directly (default: use dist/binding.js)")
    args = ap.parse_args()

    crypt = Path(args.crypt).expanduser().resolve()
    if not crypt.exists():
        print(f"[ERR] Missing: {crypt}")
        return 2

    if args.out:
        out_dir = Path(args.out).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="zalo_offline_decrypt_"))
        print(f"[INFO] using temp out_dir={out_dir}")

    if args.node:
        binding_path = Path(args.node).expanduser().resolve()
        if not binding_path.exists():
            print(f"[ERR] Missing .node: {binding_path}")
            return 2
    else:
        binding_path = Path(__file__).resolve().parents[1] / "native" / "nativelibs" / "db-cross-v4" / "dist" / "binding.js"
        if not binding_path.exists():
            print(f"[ERR] Missing binding.js: {binding_path}")
            return 2

    # Run decrypt in node (so we exercise the same addon as the app).
    env = os.environ.copy()
    env["NODE_OPTIONS"] = env.get("NODE_OPTIONS", "")
    cmd = ["node", "-e", NODE_RUNNER, str(binding_path), str(crypt), str(out_dir), args.key]
    r = subprocess.run(cmd, env=env, text=True)
    if r.returncode != 0:
        print("[ERR] Decrypt failed (see stderr above).")
        return 3

    # Validate extracted dbs (recursive, because some backups contain subfolders).
    dbs = sorted([p for p in out_dir.rglob("*.db") if p.is_file()])
    print(f"[INFO] out_dir={out_dir}")
    print(f"[INFO] extracted_db_files={len(dbs)}")
    if not dbs:
        print("[ERR] No *.db extracted.")
        return 4

    ok_header = [p for p in dbs if is_sqlite_header(p)]
    bad_header = [p for p in dbs if p not in ok_header]
    print(f"[INFO] sqlite_header_ok={len(ok_header)} sqlite_header_bad={len(bad_header)}")
    if bad_header:
        print("[WARN] bad header examples (first 10):")
        for p in bad_header[:10]:
            try:
                sz = p.stat().st_size
            except OSError:
                sz = -1
            print(f"  - {p.relative_to(out_dir)} ({sz} bytes)")

    any_integrity_ok = False
    for p in ok_header[:50]:
        ok, msg = sqlite_integrity_ok(p)
        print(f"[CHECK] {p.relative_to(out_dir)}: integrity={msg}")
        any_integrity_ok = any_integrity_ok or ok

    if not any_integrity_ok:
        print("[ERR] No DB passed PRAGMA integrity_check.")
        return 5

    print("[OK] At least one extracted DB is a valid SQLite and passes integrity_check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

