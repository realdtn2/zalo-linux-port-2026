#!/usr/bin/env python3
"""
Validate decrypted Zalo sync output (format-1).

What it checks:
- Does the target directory contain any *.db files at top-level?
- Do those files have the SQLite header ("SQLite format 3\\0")?
- Can sqlite open them read-only and run PRAGMA integrity_check?

Usage:
  python tools/check_decrypted_db.py /path/to/decrypted_output_dir
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


SQLITE_HDR = b"SQLite format 3\x00"


def is_sqlite_header(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_HDR
    except OSError:
        return False


def sqlite_integrity_ok(path: Path) -> tuple[bool, str]:
    # immutable=1 avoids journal/WAL creation attempts
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="Decrypted output directory")
    args = ap.parse_args()

    out_dir = Path(args.dir).expanduser().resolve()
    if not out_dir.exists() or not out_dir.is_dir():
        print(f"[ERR] Not a directory: {out_dir}")
        return 2

    dbs = sorted([p for p in out_dir.iterdir() if p.is_file() and p.name.endswith(".db")])
    print(f"[INFO] dir={out_dir}")
    print(f"[INFO] top_level_db_files={len(dbs)}")
    if not dbs:
        print("[ERR] No *.db files found at directory top-level.")
        print("      Zalo restore (format-1) scans only top-level *.db names like '<id>.db' or 'group_<id>.db'.")
        return 3

    ok_header = []
    bad_header = []
    for p in dbs:
        (ok_header if is_sqlite_header(p) else bad_header).append(p)

    print(f"[INFO] sqlite_header_ok={len(ok_header)} sqlite_header_bad={len(bad_header)}")
    if bad_header:
        print("[WARN] Files failing SQLite header check (first 20):")
        for p in bad_header[:20]:
            print(f"  - {p.name} ({p.stat().st_size} bytes)")

    any_integrity_ok = False
    for p in ok_header[:50]:
        ok, msg = sqlite_integrity_ok(p)
        print(f"[CHECK] {p.name}: integrity={msg}")
        if ok:
            any_integrity_ok = True

    if not any_integrity_ok:
        print("[ERR] No DB passed PRAGMA integrity_check.")
        return 4

    print("[OK] At least one DB looks valid and passes integrity_check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

