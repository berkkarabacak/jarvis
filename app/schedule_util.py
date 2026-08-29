from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _parse_field(field: str, minimum: int, maximum: int) -> set[int] | None:
    """Return allowed values, or None if '*' (all)."""
    field = (field or "").strip()
    if field == "*":
        return None
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if base == "*":
                start, end = minimum, maximum
            elif "-" in base:
                a, b = base.split("-", 1)
                start, end = int(a), int(b)
            else:
                start, end = int(base), maximum
            out.update(range(start, end + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return {v for v in out if minimum <= v <= maximum}


def _match(value: int, allowed: set[int] | None) -> bool:
    return allowed is None or value in allowed


def humanize_cron(expr: str | None, *, tz_name: str = "UTC") -> str:
    """Human-friendly description of a 5-field cron expression."""
    raw = (expr or "").strip()
    if not raw:
        return "Not scheduled"
    parts = raw.split()
    if len(parts) != 5:
        return f"Custom schedule ({raw})"

    minute, hour, dom, month, dow = parts
    tz_label = tz_name.replace("_", " ")

    # Every minute
    if parts == ["*", "*", "*", "*", "*"]:
        return "Every minute"

    # Every N minutes
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        n = minute.split("/", 1)[1]
        if n.isdigit():
            return f"Every {n} minutes"

    # Hourly at :MM
    if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute.isdigit():
        m = int(minute)
        if m == 0:
            return "Every hour"
        return f"Every hour at :{m:02d}"

    # Every N hours
    if minute.isdigit() and hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
        n = hour.split("/", 1)[1]
        if n.isdigit():
            mm = int(minute)
            if mm == 0:
                return f"Every {n} hours"
            return f"Every {n} hours at :{mm:02d}"

    # Daily at HH:MM
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow == "*":
        return f"Every day at {int(hour):02d}:{int(minute):02d} {tz_label}"

    # Weekdays Mon-Fri
    if (
        minute.isdigit()
        and hour.isdigit()
        and dom == "*"
        and month == "*"
        and dow in ("1-5", "MON-FRI", "mon-fri")
    ):
        return f"Weekdays at {int(hour):02d}:{int(minute):02d} {tz_label}"

    # Weekly on specific DOW
    dow_names = {
        "0": "Sunday",
        "7": "Sunday",
        "1": "Monday",
        "2": "Tuesday",
        "3": "Wednesday",
        "4": "Thursday",
        "5": "Friday",
        "6": "Saturday",
        "SUN": "Sunday",
        "MON": "Monday",
        "TUE": "Tuesday",
        "WED": "Wednesday",
        "THU": "Thursday",
        "FRI": "Friday",
        "SAT": "Saturday",
    }
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow.upper() in dow_names:
        return (
            f"Every {dow_names[dow.upper()]} at "
            f"{int(hour):02d}:{int(minute):02d} {tz_label}"
        )

    return f"Custom schedule ({raw})"


def next_cron_fire(
    expr: str | None,
    *,
    tz_name: str = "UTC",
    after: datetime | None = None,
) -> datetime | None:
    """Next fire time for a standard 5-field cron, in the given timezone (aware)."""
    raw = (expr or "").strip()
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 5:
        return None

    try:
        if (tz_name or "").upper() in ("UTC", "GMT", ""):
            tz = timezone.utc
        else:
            tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc


    minute_s, hour_s, dom_s, month_s, dow_s = parts
    try:
        minutes = _parse_field(minute_s, 0, 59)
        hours = _parse_field(hour_s, 0, 23)
        doms = _parse_field(dom_s, 1, 31)
        months = _parse_field(month_s, 1, 12)
        # cron DOW: 0/7=Sun .. 6=Sat; python weekday Mon=0..Sun=6
        dows_raw = _parse_field(dow_s.replace("7", "0"), 0, 6) if dow_s != "*" else None
    except Exception:
        return None

    now = after.astimezone(tz) if after else datetime.now(tz)
    # start searching from next minute
    cursor = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))

    for _ in range(366 * 24 * 60):
        if not _match(cursor.month, months):
            # jump to first day of next month
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                cursor = cursor.replace(month=cursor.month + 1, day=1, hour=0, minute=0)
            continue
        if not _match(cursor.day, doms):
            # next day
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        # DOW: convert python weekday to cron (Sun=0)
        cron_dow = (cursor.weekday() + 1) % 7
        # When both DOM and DOW are restricted, classic cron ORs them.
        # When either is *, AND applies with the other.
        if doms is not None and dows_raw is not None:
            if not (_match(cursor.day, doms) or _match(cron_dow, dows_raw)):
                cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
                continue
        elif dows_raw is not None and not _match(cron_dow, dows_raw):
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue

        if not _match(cursor.hour, hours):
            cursor = (cursor + timedelta(hours=1)).replace(minute=0)
            continue
        if not _match(cursor.minute, minutes):
            cursor = cursor + timedelta(minutes=1)
            continue
        return cursor

    return None


def schedule_info(expr: str | None, *, tz_name: str = "UTC") -> dict[str, Any]:
    human = humanize_cron(expr, tz_name=tz_name)
    nxt = next_cron_fire(expr, tz_name=tz_name)
    return {
        "cron": (expr or "").strip() or None,
        "human": human,
        "timezone": tz_name,
        "next_run_at": nxt.isoformat() if nxt else None,
        "next_run_ts": nxt.timestamp() if nxt else None,
    }


def next_cron_fires(
    expr: str | None,
    *,
    tz_name: str = "UTC",
    after: datetime | None = None,
    limit: int = 10,
    within_hours: float | None = None,
) -> list[datetime]:
    """Next N fire times for a 5-field cron (aware datetimes). Read-only helper."""
    limit = max(0, min(int(limit), 200))
    if limit == 0:
        return []
    cursor_after = after
    end: datetime | None = None
    if within_hours is not None and within_hours >= 0:
        base = after or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        end = base + timedelta(hours=float(within_hours))
    out: list[datetime] = []
    for _ in range(limit):
        nxt = next_cron_fire(expr, tz_name=tz_name, after=cursor_after)
        if nxt is None:
            break
        if end is not None and nxt > end:
            break
        out.append(nxt)
        cursor_after = nxt
    return out
