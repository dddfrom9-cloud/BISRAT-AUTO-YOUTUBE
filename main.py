import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEDULE_PATH = Path("schedule.json")
STATE_PATH = Path("state.json")


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else dict(default)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def should_run_upload() -> tuple[bool, dict]:
    schedule = load_json(
        SCHEDULE_PATH,
        {
            "mode": "repeat",
            "intervalHours": 6,
            "intervalMinutes": 0,
            "active": False,
            "nextRunAt": None,
            "lastRunAt": None,
            "updatedAt": None,
        },
    )
    manual = os.environ.get("MANUAL_TRIGGER", "").lower() == "true"
    if manual:
        return True, schedule

    if not schedule.get("active"):
        return False, schedule

    next_run_str = schedule.get("nextRunAt")
    if not next_run_str:
        return False, schedule

    try:
        next_run = datetime.fromisoformat(next_run_str.replace("Z", "+00:00"))
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
    except ValueError:
        return False, schedule

    now = datetime.now(timezone.utc)
    return now >= next_run, schedule


def advance_schedule_after_upload(schedule: dict) -> dict:
    now = datetime.now(timezone.utc)
    schedule["lastRunAt"] = now.isoformat()
    schedule["updatedAt"] = now.isoformat()

    mode = schedule.get("mode", "repeat")
    if mode == "once":
        # One-time mode: publish one video, then stop
        schedule["active"] = False
        schedule["nextRunAt"] = None
    else:
        # Repeat mode: schedule next run from current time
        hours = max(0, int(schedule.get("intervalHours", 6) or 0))
        minutes = max(0, min(59, int(schedule.get("intervalMinutes", 0) or 0)))
        delta = timedelta(hours=hours, minutes=minutes)
        if delta.total_seconds() <= 0:
            delta = timedelta(hours=1)
        schedule["active"] = True
        schedule["nextRunAt"] = (now + delta).isoformat()

    save_json(SCHEDULE_PATH, schedule)
    return schedule
