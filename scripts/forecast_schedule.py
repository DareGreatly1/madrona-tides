"""Decide whether a Daily forecast run should rebuild and deploy.

A git commit is not a successful publish. Scheduled runs skip only when
the live Pages version.json is already today's America/Los_Angeles date.
If the repo has today's forecast but the live page does not, the run
uploads the committed site and deploys it without rebuilding. A manual
workflow_dispatch always rebuilds and deploys.

    python scripts/forecast_schedule.py

Writes rebuild= and deploy= to $GITHUB_OUTPUT when that file is set.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site

ROOT = build_site.ROOT
LIVE_VERSION_URL = "https://daregreatly1.github.io/madrona-tides/version.json"


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


def read_live_run_date(url: str, opener=None) -> str | None:
    """Pacific run_date on the public page, or None if it cannot be read.

    None means unknown. Callers must not treat an unknown page as current.
    """
    if not url:
        return None
    stamped = url + ("&" if "?" in url else "?") + "t=" + str(int(time.time()))
    request = urllib.request.Request(
        stamped,
        headers={
            "User-Agent": "MadronaBeachTides/1.0 (forecast schedule check)",
            "Cache-Control": "no-cache",
            "Accept": "application/json",
        },
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=20) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    run_date = str(payload.get("run_date") or "").strip()
    return run_date or None


def publication_plan(event_name: str, root: Path, today: str, live_run_date: str | None) -> tuple[bool, bool]:
    """Return (rebuild, deploy).

    Manual runs always do both. A scheduled run rebuilds only when the
    repo does not already contain today's forecast, and it deploys unless
    the live page is already that date.
    """
    if event_name != "schedule":
        return True, True
    if live_run_date == today:
        return False, False
    if already_published(root, today):
        return False, True
    return True, True


def write_github_output(rebuild: bool, deploy: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"rebuild={'true' if rebuild else 'false'}\n")
        fh.write(f"deploy={'true' if deploy else 'false'}\n")


def main() -> None:
    today = build_site.pacific_now().date().isoformat()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    live_url = os.environ.get("PAGES_VERSION_URL", LIVE_VERSION_URL)
    live_run_date = read_live_run_date(live_url)
    rebuild, deploy = publication_plan(event_name, ROOT, today, live_run_date)
    write_github_output(rebuild, deploy)
    if live_run_date is None:
        print(f"Could not read the live page date from {live_url}. Not treating the page as current.")
    else:
        print(f"Live page run_date is {live_run_date}.")
    if rebuild and deploy:
        print(f"Building the {today} forecast ({event_name or 'local'}).")
    elif deploy:
        print(
            f"The repo already has the {today} forecast, but the live page does not. "
            "Deploying the committed site without rebuilding."
        )
    else:
        print(f"The live page already has the {today} forecast. Skipping the rebuild and deploy.")


if __name__ == "__main__":
    main()
