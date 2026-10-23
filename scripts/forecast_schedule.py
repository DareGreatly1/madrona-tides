"""Decide whether a Daily forecast run should rebuild.

Scheduled runs skip when today's America/Los_Angeles forecast is already
in site/version.json or data/history.csv. A manual workflow_dispatch
always rebuilds.

    python scripts/forecast_schedule.py

Writes publish=true or publish=false to $GITHUB_OUTPUT when that file is set.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site

ROOT = build_site.ROOT


def already_published(root: Path, today: str) -> bool:
    """True when version.json or history.csv records this Pacific date.

    version.json is the stamp the open page polls. history.csv is the
    log committed with it. A row's high-tide time is not the publish
    date: yesterday's run already lists some of today's tides.
    """
    version_path = root / "site" / "version.json"
    if version_path.exists():
        try:
            payload = json.loads(version_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and str(payload.get("run_date") or "") == today:
            return True

    history_path = root / "data" / "history.csv"
    if not history_path.exists():
        return False
    try:
        with history_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if (row.get("run_date") or "").strip() == today:
                    return True
    except OSError:
        return False
    return False


def should_publish(event_name: str, root: Path, today: str) -> bool:
    """Manual runs always build. A schedule builds only if today is missing."""
    if event_name != "schedule":
        return True
    return not already_published(root, today)


def write_github_output(publish: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    line = f"publish={'true' if publish else 'false'}\n"
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def main() -> None:
    today = build_site.pacific_now().date().isoformat()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    publish = should_publish(event_name, ROOT, today)
    write_github_output(publish)
    if publish:
        print(f"Building the {today} forecast ({event_name or 'local'}).")
    else:
        print(f"Today's forecast ({today}) is already published. Skipping the rebuild.")


if __name__ == "__main__":
    main()
