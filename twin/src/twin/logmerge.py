"""Merge the part files of one run into the single log file for the repo's `logs/` folder.

    python -m twin.logmerge run-42-001
    python -m twin.logmerge run-42-001 --parts ../brain/run-logs/run-42-001.brain.jsonl ../guardian/run-logs/run-42-001.guardian.jsonl

The Twin's own part file is found automatically. Add the other layers' part files with --parts. Running it again is safe:
the merged file is rebuilt from the parts every time.
"""
import argparse
import sys
from pathlib import Path

from .runlog import merge_parts, read_part
from .settings import load_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin.logmerge", description=__doc__.split("\n\n")[0])
    ap.add_argument("run_id", help="for example run-42-001")
    ap.add_argument("--parts", nargs="*", default=[], help="part files of the other layers")
    ap.add_argument("--parts-dir", help="where the Twin's part file is (default: from the config)")
    ap.add_argument("--out", help="folder for the merged file (default: from the config)")
    a = ap.parse_args(argv)
    cfg = load_config().logging
    twin_part = Path(a.parts_dir or cfg.parts_dir) / f"{a.run_id}.twin.jsonl"
    out = Path(a.out or cfg.merged_dir) / f"{a.run_id}.jsonl"
    files = [twin_part, *map(Path, a.parts)]
    missing = [str(f) for f in files if not f.exists()]
    if twin_part in [Path(m) for m in missing]:
        print(f"No Twin part file at {twin_part}. Was the Twin run from the twin/ folder?", file=sys.stderr)
        return 1
    for m in missing:
        print(f"Note: {m} does not exist, skipped.", file=sys.stderr)
    try:
        merged = merge_parts([f for f in files if f.exists()], out)
    except ValueError as e:
        print(f"Not merged: {e}", file=sys.stderr)
        return 1
    n = len(read_part(merged)[0])
    print(f"Wrote {merged} ({n} events from {len(files) - len(missing)} part file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
