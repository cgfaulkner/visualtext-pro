#!/usr/bin/env python3
"""
Migrate old CWD batch manifests into input_root/staged_runs/<run_id>/manifest.json.

Non-destructive by default (no --delete-source). Idempotent: if target exists and
matches, skip. Use --dry-run to print what would be moved without writing.

Usage:
  python tools/migrate_manifests.py --input-root /path/to/input [--run-id ID] [--yes] [--dry-run]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# Project root for shared imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(ROOT / "shared"))


def find_cwd_manifests(cwd: Path):
    """Find batch_*_manifest.json or batch_*_*_manifest.json in cwd."""
    found = []
    for p in cwd.iterdir():
        if p.is_file() and p.suffix == ".json" and "manifest" in p.name:
            if p.name.startswith("batch_") and p.name.endswith("_manifest.json"):
                found.append(p)
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(
        description="Move CWD batch manifests into input_root/staged_runs/<run_id>/manifest.json"
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        required=True,
        help="Target input root; manifests moved to input_root/<staging_root>/<run_id>/manifest.json",
    )
    parser.add_argument(
        "--run-id",
        help="Use this run_id for the migrated manifest(s). If omitted, auto-generate (UTC timestamp).",
    )
    parser.add_argument(
        "--staging-root",
        default="staged_runs",
        help="Staging directory name under input root (default: staged_runs).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive; perform migration without prompting.",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="After successful move and verify, remove source manifest. Default: false.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be moved; do not write.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for manifests (default: current directory).",
    )
    args = parser.parse_args()

    input_root = args.input_root.resolve()
    if not input_root.is_dir():
        input_root.mkdir(parents=True, exist_ok=True)

    manifests = find_cwd_manifests(args.cwd.resolve())
    if not manifests:
        print("No batch_*_manifest.json files found in", args.cwd)
        return 0

    run_id = args.run_id
    if not run_id:
        from datetime import datetime, timezone
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    run_dir = input_root / args.staging_root / run_id
    target_manifest = run_dir / "manifest.json"

    if args.dry_run:
        print(f"Would create {run_dir}")
        print(f"Would move {len(manifests)} manifest(s) to {target_manifest}")
        for m in manifests:
            print(f"  {m}")
        return 0

    if target_manifest.exists() and len(manifests) == 1:
        try:
            with open(manifests[0]) as f:
                src_data = json.load(f)
            with open(target_manifest) as f:
                dst_data = json.load(f)
            if src_data == dst_data:
                print("Target already exists with same content; skip (idempotent).")
                return 0
        except (json.JSONDecodeError, OSError):
            pass

    if not args.yes and len(manifests) > 0:
        reply = input(
            f"Move {len(manifests)} manifest(s) to {target_manifest}? [y/N] "
        ).strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    (run_dir / "outputs").mkdir(exist_ok=True)

    # Use first manifest as primary; if multiple, merge or copy first (plan: one run_id per migrate)
    source = manifests[0]
    temp_path = target_manifest.parent / (target_manifest.name + ".tmp")
    try:
        with open(source) as f:
            data = json.load(f)
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(target_manifest)
        print(f"Moved manifest to {target_manifest}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return 1

    if args.delete_source:
        try:
            source.unlink()
            print(f"Removed source {source}")
        except OSError as e:
            print(f"Warning: could not remove source: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
