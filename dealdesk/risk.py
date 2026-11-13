"""Deal-level risk checks against the creator profile. All arithmetic and
policy comparisons live here, in plain code."""
import re
from datetime import date

from . import fmt
from .models import flag

BELOW_RATE_WARN_PCT = 5
BELOW_RATE_HIGH_PCT = 25
SHORT_NOTICE_DAYS = 7
LOW_GIFTING_COVERAGE = 0.25


def market_value(terms, profile):
    """What the creator's rate card says this work is worth, in INR."""
    rates = profile.get("base_rates_inr", {})
    total, parts = 0, []
    unlisted = []
    for d in terms.get("deliverables") or []:
        rate = rates.get(d.get("rate_key"))
        if rate is None:
            kind = f"{d.get('platform', '')} {d.get('type', '')}".strip() or "deliverable"
            unlisted.append(f"{d.get('count', 1)} x {kind}")
            continue
        total += rate * d["count"]
        parts.append(f"{d['count']} x {fmt.inr(rate)}")

    partial = bool(unlisted)
    value = total if parts else None
    out = {"market_value_inr": value, "breakdown": " + ".join(parts), "partial": partial,
           "unlisted": unlisted, "offered_inr": terms.get("fee_inr"), "delta_pct": None}
    if value and terms.get("fee_inr"):
        out["delta_pct"] = round((terms["fee_inr"] - value) / value * 100, 1)
    return out


def included_months(profile):
    m = re.search(r"(\d+)\s*months?", profile.get("usage_rights_policy", ""))
    return int(m.group(1)) if m else 3


def deal_flags(terms, history, market, profile, today, category):
    flags = []
    fee, cur = terms.get("fee_inr"), terms.get("fee_currency")

    delta = market["delta_pct"]
    if delta is not None and delta <= -BELOW_RATE_WARN_PCT:
        sev = "high" if delta <= -BELOW_RATE_HIGH_PCT else "warn"
        note = " (excludes unlisted deliverables)" if market.get("partial") else ""
        flags.append(flag("below_rate", sev,
                          f"Offer of {fmt.money(terms['fee_amount'], cur)} is {abs(delta):.0f}% below your rate card "
                          f"for this work ({fmt.inr(market['market_value_inr'])}: {market['breakdown']}{note}).",
                          offered=fee, rate_card=market["market_value_inr"]))
    elif delta is not None and delta > 0:
        flags.append(flag("above_rate", "info",
                          f"Offer is {delta:.0f}% above your rate card ({fmt.inr(market['market_value_inr'])}).",
                          offered=fee, rate_card=market["market_value_inr"], delta_pct=delta))

    if market.get("partial") and market.get("unlisted"):
        unlisted_text = ", ".join(market["unlisted"])
        flags.append(flag("partial_rate_card", "info",
                          f"Your rate card does not list rates for {unlisted_text}. "
                          f"Market value ({fmt.inr(market['market_value_inr']) if market['market_value_inr'] else 'not available'}) "
                          "reflects known deliverables only.",
                          unlisted=market["unlisted"]))

    for h in history:
        if h["field"] == "fee" and h["to_inr"] < h["from_inr"]:
            drop = (h["from_inr"] - h["to_inr"]) / h["from_inr"] * 100
            flags.append(flag("terms_worsened", "warn",
                              f"The brand cut its offer from {fmt.inr(h['from_inr'])} to {fmt.inr(h['to_inr'])} "
                              f"(-{drop:.0f}%) in its follow-up of {fmt.day(h['date'])}.",
                              original=h["from_inr"], latest=h["to_inr"]))

    u = terms.get("usage") or {}
    limit = included_months(profile)
    problems = []
    if u.get("perpetual"):
        problems.append("perpetual usage")
    elif u.get("months") and u["months"] > limit:
        problems.append(f"{u['months']} months of usage")
    if u.get("whitelisting"):
        problems.append("whitelisting (ads run from your handle)")
    if problems:
        flags.append(flag("usage_rights", "high",
                          f"Asks for {' and '.join(problems)}. Your policy includes {limit} months of paid-ad usage; "
                          "longer or perpetual rights must be priced separately, and none of that is in this fee."))

    if terms.get("payment_type") == "gifting" and terms.get("product_value_inr") and market["market_value_inr"]:
        ratio = terms["product_value_inr"] / market["market_value_inr"]
        if ratio < LOW_GIFTING_COVERAGE:
            flags.append(flag("gifting_low_value", "high",
                              f"Only product ({fmt.inr(terms['product_value_inr'])}) for work your rate card puts at "
                              f"{fmt.inr(market['market_value_inr'])}; the product covers {ratio:.0%} of it."))

    first = terms.get("window_start") or terms.get("deadline")
    end = terms.get("deadline")
    if end and date.fromisoformat(end) < today:
        n = (today - date.fromisoformat(end)).days
        flags.append(flag("impossible_deadline", "high",
                          f"The deadline ({fmt.day(end)}) passed {n} day{'s' * (n != 1)} ago. "
                          "It is either a mistake or a leftover from an old brief."))
    elif first:
        n = (date.fromisoformat(first) - today).days
        if n <= SHORT_NOTICE_DAYS:
            when = "opens" if terms.get("window_start") else "is due"
            flags.append(flag("short_notice", "warn",
                              f"The first slot {when} in {max(n, 0)} day{'s' * (n != 1)} ({fmt.day(first)})"
                              + (f", window closes {fmt.day(end)}." if terms.get("window_start") and end else ".")))

    if terms.get("fee_currency_assumed") and fee:
        flags.append(flag("currency_assumed", "info", "No currency was given with the amount; assumed rupees."))
    if category == "deal_offer" and fee and not terms.get("payment_terms_stated"):
        flags.append(flag("payment_terms_unstated", "info", "Payment timing and method are not stated."))
    return flags
