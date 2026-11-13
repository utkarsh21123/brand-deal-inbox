"""Small formatting helpers. Everything the creator reads goes through these."""
import re
from datetime import date

_CTRL = re.compile(r"[\x00-\x1f\x7f`*_#<>\[\]|]")


def inr(n):
    """Indian digit grouping: 120000 -> ₹1,20,000."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def money(amount, currency):
    if amount is None:
        return "not stated"
    if currency == "USD":
        return f"${int(round(amount)):,}"
    return inr(amount)


def day(iso):
    """'2026-11-25' -> '25 Nov'."""
    if not iso:
        return "not stated"
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


_NAMES = {"instagram_reel": "Instagram reel", "instagram_story": "Instagram story",
          "youtube_integration": "YouTube integration", "youtube_dedicated_video": "dedicated YouTube video",
          "youtube_shoutout": "YouTube shoutout"}


def deliverables(items):
    """[{instagram reel x2}, {story x3}] -> '2 Instagram reels + 3 Instagram stories'."""
    parts = []
    for d in items or []:
        name = _NAMES.get(f"{d['platform']}_{d['type']}", f"{d['platform']} {d['type']}".strip())
        name = name.replace("story", "stories") if d["count"] != 1 and name.endswith("story") else name
        parts.append(f"{d['count']} {name}{'s' if d['count'] != 1 and not name.endswith('stories') else ''}")
    return " + ".join(parts) if parts else "not stated"


def clean(text, limit=80):
    """Strip markup and control characters from text that came out of an email.

    Brand names and contact names end up in Markdown reports, so anything
    that could render as a link, heading or table is removed first.
    """
    if text is None:
        return ""
    return _CTRL.sub("", str(text)).strip()[:limit]
