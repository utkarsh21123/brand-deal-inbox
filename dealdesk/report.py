"""Markdown output for the creator: a summary and a file of draft replies."""
from datetime import date

from . import fmt

_ACTION = {"accept": "Accept", "negotiate": "Negotiate", "ask_for_details": "Ask for details",
           "decline": "Decline", "report": "Report", "ignore": "Ignore"}
_URGENT = {"short_notice", "impossible_deadline"}


def _usage_line(u):
    if not u.get("stated"):
        return "not stated"
    bits = []
    if u.get("perpetual"):
        bits.append("perpetual")
    elif u.get("months"):
        bits.append(f"{u['months']} months")
    if u.get("whitelisting"):
        bits.append("whitelisting")
    if u.get("all_media"):
        bits.append("all media")
    return ", ".join(bits)


def _when(t):
    if t["window_start"] and t["deadline"]:
        return f"{fmt.day(t['window_start'])} to {fmt.day(t['deadline'])}"
    if t["deadline"]:
        return f"by {fmt.day(t['deadline'])}"
    return t["deadline_text"] or "not stated"


def _fee(t):
    if t["fee_amount"]:
        s = fmt.money(t["fee_amount"], t["fee_currency"])
        return s + (f" (about {fmt.inr(t['fee_inr'])})" if t["fee_currency"] == "USD" else "")
    if t["payment_type"] == "gifting":
        v = f" worth {fmt.inr(t['product_value_inr'])}" if t["product_value_inr"] else ""
        return "free product" + v + ", no fee"
    return "not stated"


def _deal_block(d):
    t = d.terms
    who = fmt.clean(d.brand) + (f" (via {fmt.clean(d.agency)})" if d.agency else "")
    n = len(d.emails)
    out = [f"### {who}: {_ACTION[d.action]}",
           f"{n} email{'s' * (n != 1)} ({', '.join(d.emails)}). {d.action_reason}", ""]
    parts = []
    if t["deliverables"]:
        parts.append(fmt.deliverables(t["deliverables"]))
    if t["fee_amount"] or t["payment_type"] == "gifting":
        parts.append(_fee(t))
    if t["deadline"] or t["deadline_text"]:
        parts.append(_when(t))
    if t["usage"].get("stated"):
        parts.append("usage: " + _usage_line(t["usage"]))
    out += [f"- **Offer:** " + ("; ".join(parts) if parts else "no deliverables, fee or dates given")]
    if d.market["market_value_inr"]:
        if d.action == "decline" and d.market.get("partial"):
            pass
        else:
            delta_str = ""
            if d.market.get("delta_pct") is not None and d.market["delta_pct"] > 0:
                delta_str = f" (offer is {d.market['delta_pct']:.0f}% above your rate)"
            card_label = "Your rate card for known deliverables" if d.market.get("partial") else "Your rate card for this"
            out += [f"- **{card_label}:** {fmt.inr(d.market['market_value_inr'])}{delta_str}"]
    for h in d.history:
        if h["field"] == "fee":
            out += [f"- **Changed:** fee went from {fmt.inr(h['from_inr'])} to {fmt.inr(h['to_inr'])} on {fmt.day(h['date'])}"]
    loud = [f for f in d.flags if f["severity"] != "info"]
    for f in loud:
        out += [f"- **{f['severity'].title()}:** {f['message']}"]
    quiet = [f for f in d.flags if f["severity"] == "info"]
    if quiet:
        out += ["- Also: " + " ".join(f["message"] for f in quiet)]
    if d.draft:
        out += [f"- Draft reply: see {d.id} in `drafts.md`"]
    return "\n".join(out) + "\n"


def _urgent(d):
    return d.action == "accept" or any(f["code"] in _URGENT for f in d.flags)


def summary(results, deals, profile):
    today = date.fromisoformat(profile["today"])
    first = profile["name"].split()[0]
    live = [d for d in deals if d.action in ("accept", "negotiate", "ask_for_details")]
    declines = [d for d in deals if d.action == "decline"]
    junk = [r for r in results if r.junk_action]
    scams = [r for r in junk if r.junk_action == "report"]

    out = [f"# Brand inbox for {first}, {today.day} {today.strftime('%B %Y')}", "",
           f"{len(results)} emails came in. {len(live)} are worth replying to, {len(declines)} you should "
           f"decline, and {len(junk)} are scams or junk.", ""]

    today_list = [d for d in live if _urgent(d)]
    week_list = [d for d in live if not _urgent(d)]
    if today_list:
        out += ["## Needs attention today", ""] + [_deal_block(d) for d in today_list]
    if week_list:
        out += ["## Reply this week", ""] + [_deal_block(d) for d in week_list]
    if declines:
        out += ["## Politely decline", ""]
        for d in declines:
            reason = next((f["message"] for f in d.flags if f["severity"] == "critical"), d.action_reason)
            out += [f"- **{fmt.clean(d.brand)}** ({', '.join(d.emails)}): {reason}"]
        out += [""]
    if scams:
        out += ["## Do not engage: report these", ""]
        for r in scams:
            why = next((f["message"] for f in r.flags if f["severity"] == "critical"), r.category_reason)
            out += [f"- **{r.id}, {fmt.clean(r.subject, 60)}** (from {fmt.clean(r.sender, 50)}): {why}"]
        out += [""]
    ignored = [r for r in junk if r.junk_action == "ignore"]
    if ignored:
        out += ["## Ignore", ""] + [f"- {r.id}, {fmt.clean(r.subject, 60)}: {r.category_reason}" for r in ignored] + [""]
    out += ["---", "Drafts are suggestions for you to edit. Nothing has been sent."]
    return "\n".join(out) + "\n"


def drafts_file(deals):
    out = ["# Draft replies", "", "Review and edit before sending. Nothing here has been sent.", ""]
    for d in deals:
        if not d.draft:
            continue
        out += [f"## {d.id}: {fmt.clean(d.brand)} ({_ACTION[d.action]})", f"To: {fmt.clean(d.contact_email, 80)}", "",
                "```", d.draft, "```", ""]
    return "\n".join(out)
