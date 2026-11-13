"""Amounts and dates. This is plain code on purpose: "1,20,000" and "3 lakh"
must come out as exact numbers, and a model should never be the one deciding
what a figure is worth."""
import re
from dataclasses import dataclass
from datetime import date, timedelta

_UNITS = {"k": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
          "lacs": 100_000, "crore": 10_000_000}
_CURRENCY = {"inr": "INR", "rs": "INR", "rs.": "INR", "₹": "INR", "rupees": "INR",
             "usd": "USD", "$": "USD", "us$": "USD", "dollars": "USD"}

_NUM = r"(?P<num>\d[\d,]*(?:\.\d+)?)"
_UNIT = r"(?:\s*(?P<unit>k|lakhs?|lacs?|crore)\b)?"
_PREFIX = re.compile(r"(?<![A-Za-z])(?P<cur>INR|Rs\.?|₹|USD|US\$|\$)\s*" + _NUM + _UNIT, re.I)
_SUFFIX = re.compile(_NUM + _UNIT + r"\s*(?P<cur>INR|rupees|USD|dollars)\b", re.I)
_BARE_K = re.compile(r"\b(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>k)\b", re.I)


@dataclass
class Amount:
    value: float
    currency: str          # "INR" or "USD"
    assumed: bool          # True when the email gave no currency at all
    start: int
    end: int


def _to_value(num, unit):
    v = float(num.replace(",", "").rstrip("."))
    return v * _UNITS[unit.lower()] if unit else v


def find_amounts(text):
    found = []
    for rx in (_PREFIX, _SUFFIX):
        for m in rx.finditer(text):
            cur = _CURRENCY[m.group("cur").lower()]
            found.append(Amount(_to_value(m.group("num").rstrip(","), m.group("unit")),
                                cur, False, m.start(), m.end()))
    for m in _BARE_K.finditer(text):
        if any(a.start <= m.start() < a.end for a in found):
            continue
        # "25k" with no currency: Indian creator, Indian brand, assume rupees and say so.
        found.append(Amount(_to_value(m.group("num"), m.group("unit")), "INR", True,
                            m.start(), m.end()))
    return sorted(found, key=lambda a: a.start)


def to_inr(amount, currency, usd_inr):
    if amount is None:
        return None
    return amount * usd_inr if currency == "USD" else amount


def usd_rate(profile, default=84.0):
    m = re.search(r"1\s*USD\s*=\s*(\d+(?:\.\d+)?)\s*INR", profile.get("currency_note", ""))
    return float(m.group(1)) if m else default


_MONTH = (r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_RANGE = re.compile(r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s*(?:-|–|to|and)\s*"
                    r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r"\b", re.I)
_SINGLE = re.compile(r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r"\b", re.I)
_RELATIVE = re.compile(r"\bwithin\s+(?:\d+|a|one|two|three)\s+(?:day|week|month)s?\s+of\s+\w+", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _resolve(day, mon, ref):
    month = _MONTHS.index(mon[:3].lower()) + 1
    d = date(ref.year, month, day)
    # A date more than ~6 months behind the email is almost certainly next year.
    return d.replace(year=ref.year + 1) if d < ref - timedelta(days=180) else d


def find_dates(text, ref):
    """Return (window_start, deadline, relative_text). Dates are ISO strings.

    `ref` is the date the email arrived; it decides which year a bare
    "25 November" means.
    """
    try:
        m = _RANGE.search(text)
        if m:
            return (_resolve(int(m["d1"]), m["mon"], ref).isoformat(),
                    _resolve(int(m["d2"]), m["mon"], ref).isoformat(), None)
        m = _SINGLE.search(text)
        if m:
            return None, _resolve(int(m["d"]), m["mon"], ref).isoformat(), None
    except ValueError:  # "31 February" and friends
        pass
    m = _RELATIVE.search(text)
    return None, None, (m.group(0) if m else None)


def sentence_at(text, pos):
    start = max(text.rfind(". ", 0, pos), text.rfind("! ", 0, pos), text.rfind("? ", 0, pos)) + 1
    ends = [i for i in (text.find(". ", pos), text.find("! ", pos), text.find("? ", pos)) if i != -1]
    return text[start:(min(ends) + 1) if ends else len(text)]
