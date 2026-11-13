"""Draft replies. Templates filled from verified numbers.

The model never writes these. A reply the creator might send as-is should
not contain an amount that came from a language model, so every figure here
comes from parsed terms and the rate card. The creator reviews every draft;
nothing is sent.
"""
from . import fmt, parsing, risk

_ASK = {"deliverables": "what you would like me to create (formats, number of posts, platform)",
        "fee": "your budget for this",
        "timeline": "the timeline and any posting dates",
        "usage": "whether you need usage rights (for example paid ads) and for how long",
        "payment_terms": "payment terms (when and how I would be paid)"}


def _lines(*parts):
    return "\n\n".join(p for p in parts if p)


def _ask_list(items):
    items = [_ASK[i] for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return f"Could you confirm {items[0]}?"
    return "Could you confirm:\n" + "\n".join(f"- {i}" for i in items)


def reply(deal, missing, profile):
    """Return a draft, or None when replying would be a mistake (scams) or pointless."""
    codes = {f["code"]: f for f in deal.flags}
    me = profile["name"].split()[0]
    hi = f"Hi {deal.contact_name}," if deal.contact_name else "Hi,"
    t, brand = deal.terms, deal.brand
    work = fmt.deliverables(t["deliverables"])

    if deal.action == "decline":
        if "exclusivity_conflict" in codes:
            d = codes["exclusivity_conflict"]["data"]
            until = fmt.day(d["until"]) + " " + d["until"][:4]
            return _lines(hi, f"Thanks for thinking of me for {brand}. I'm under an exclusivity commitment in the "
                          f"{d['category']} category until {until}, so I can't take this on right now.",
                          "If the timing works after that date, I'd be happy to talk again.", f"Best,\n{me}")
        return _lines(hi, f"Thanks for reaching out about {brand}. This isn't a category I work with, so I'll "
                      "have to pass.", f"Wishing you a great campaign.\n{me}")

    if deal.action == "ask_for_details":
        asks = [m for m in missing if m != "usage" or not t["usage"].get("stated")]
        body = []
        if "impossible_deadline" in codes:
            body.append(f"The brief says the content should be live by {fmt.day(t['deadline'])}, which has already "
                        "passed. Could you confirm the date you actually need?")
            asks = [a for a in asks if a != "timeline"]
        intro = f"Thanks for reaching out about {brand}." + (
            f" The {fmt.money(t['fee_amount'], t['fee_currency'])} budget is noted." if t["fee_amount"] else "")
        asks = [a for a in asks if a != "payment_terms"]
        if t["fee_amount"] and "impossible_deadline" not in codes:
            asks.append("payment_terms")
        return _lines(hi, intro, *body, _ask_list(asks) if asks else "", f"Best,\n{me}")

    if deal.action == "negotiate":
        if t.get("language") == "hinglish":
            return _hinglish_negotiation(deal, me, work)
        points = []
        mv = deal.market["market_value_inr"]
        offer = fmt.money(t["fee_amount"], t["fee_currency"])
        if "below_rate" in codes:
            ask = _in_currency(mv, t["fee_currency"], parsing.usd_rate(profile))
            moved = ""
            if "terms_worsened" in codes:
                d = codes["terms_worsened"]["data"]
                moved = f"I noticed the budget moved from {fmt.inr(d['original'])} to {fmt.inr(d['latest'])}. "
            points.append(f"{moved}My rate for {work} is {fmt.inr(mv)}, so the current offer of {offer} is below "
                          f"what I can do. I'd need {ask} to go ahead.")
        if "usage_rights" in codes:
            points.append(f"On usage: my fee includes up to {risk.included_months(profile)} months of paid-ad usage. "
                          "Perpetual usage and "
                          "whitelisting are not included and are priced separately. Could you tell me how long "
                          "and on which channels you need them? I'll send a quote.")
        if "gifting_low_value" in codes:
            points.append(f"I do paid collaborations, and a product alone doesn't cover {work}. Is there a "
                          "budget for this? If so, send it over and I'll tell you what I can do.")
        extra = [m for m in missing if m in ("timeline", "usage") and not ("usage_rights" in codes and m == "usage")]
        extra.append("payment_terms")
        return _lines(hi, f"Thanks for reaching out about {brand}.", *points, _ask_list(extra), f"Best,\n{me}")

    if deal.action == "accept":
        return _lines(hi, f"Thanks for the offer. I'm happy to go ahead with {work} for "
                      f"{fmt.money(t['fee_amount'], t['fee_currency'])}.",
                      "Could you send a written agreement covering deliverables, fee, payment terms and usage "
                      "rights before we start?", f"Best,\n{me}")
    return None


def _in_currency(inr_value, currency, usd_inr=84.0):
    return fmt.money(inr_value / usd_inr, "USD") if currency == "USD" else fmt.inr(inr_value)


def _hinglish_negotiation(deal, me, work):
    mv = fmt.inr(deal.market["market_value_inr"]) if deal.market["market_value_inr"] else None
    offer = fmt.money(deal.terms["fee_amount"], deal.terms["fee_currency"])
    price = (f"{work} ka mera rate {mv} hai, aur abhi ka budget ({offer}) us se kam hai. "
             f"Kya aap {mv} tak ja sakte hain?") if mv else "Kya aap apna budget thoda badha sakte hain?"
    return _lines(f"Namaste{' ' + deal.contact_name if deal.contact_name else ''},",
                  f"Message ke liye dhanyavaad! {deal.brand} ke saath kaam karne mein mujhe interest hai. {price}",
                  "Saath hi timeline aur content usage (ads mein kitne time tak use karenge) bhi bata dijiye, "
                  "aur payment kab aur kaise hoga.", f"Dhanyavaad,\n{me}")
