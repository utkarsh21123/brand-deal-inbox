"""Glue: analyse each email, group into deals, decide what to do."""
import re
from datetime import date

from . import drafts, extract, fmt, llm, parsing, risk, signals
from .models import Deal, EmailResult, Extraction, flag

_COLLAB_WORDS = re.compile(r"collab|partner|campaign|brief|sponsor|work with|feature|ambassador", re.I)


def _norm(s):
    return re.sub(r"and", "", re.sub(r"[^a-z0-9]", "", (s or "").lower()))


# ---------------------------------------------------------------- one email

def _grounded_fee(amount, body):
    """A model-reported fee only counts if the number is actually in the email."""
    if amount in {a.value for a in parsing.find_amounts(body)}:
        return True
    return str(int(amount)) in re.sub(r"[,\s]", "", body)


def merge(model_ex, rules_ex, email, profile):
    """Take model output where it passes checks, rules output otherwise."""
    if model_ex is None:
        return rules_ex
    body = email.get("body", "")
    hay = _norm(f"{email.get('subject', '')}{body}{email.get('from', '')}")
    ex = rules_ex

    for name in ("brand", "agency"):
        v = getattr(model_ex, name)
        if v and _norm(v) in hay:                 # a name that appears nowhere in the email is made up
            setattr(ex, name, v)
    ex.contact_name = model_ex.contact_name or ex.contact_name
    ex.language = model_ex.language if model_ex.language != "english" else ex.language
    if model_ex.deliverables:
        ex.deliverables = model_ex.deliverables
    if model_ex.fee_amount:
        if _grounded_fee(model_ex.fee_amount, body):
            ex.fee_amount, ex.fee_currency = model_ex.fee_amount, model_ex.fee_currency
            ex.fee_currency_assumed = model_ex.fee_currency_assumed
            ex.payment_type = "cash"
        else:
            ex.notes.append(f"model reported a fee of {model_ex.fee_amount:g} that is not in the email; dropped")
    elif model_ex.payment_type in ("gifting", "mixed") and not ex.fee_amount:
        ex.payment_type = model_ex.payment_type
    ex.product_value_inr = model_ex.product_value_inr or ex.product_value_inr
    ex.window_start = model_ex.window_start or ex.window_start
    ex.deadline = model_ex.deadline or ex.deadline
    ex.deadline_text = model_ex.deadline_text or ex.deadline_text
    if model_ex.usage.stated:
        ex.usage = model_ex.usage
    ex.product_category = model_ex.product_category or ex.product_category
    ex.mentions_attachment = ex.mentions_attachment or model_ex.mentions_attachment
    ex.fee_inr = parsing.to_inr(ex.fee_amount, ex.fee_currency, parsing.usd_rate(profile))
    return ex


def decide_category(sig, ex, profile, text, model_category=None):
    """Returns (category, reason, hard). `hard` means a rule decided, not the model."""
    if sig.injection:
        return "scam_or_phishing", "contains instructions aimed at AI tools", True
    if sig.pay_to_join:
        return "scam_or_phishing", "asks the creator to pay a fee to join or unlock something", True
    if signals.phishing(sig):
        return "scam_or_phishing", "threatens the account and pushes a link from a look-alike sender", True
    if sig.personal_data_request:
        return "scam_or_phishing", "asks for personal contact or financial details", True
    hits = signals.content_rule_hits(sig, profile)
    if hits:
        return "not_a_fit", f"breaks a content rule: {hits[0]}", True
    today = date.fromisoformat(profile["today"])
    clash = signals.exclusivity_conflicts(profile, ex.brand, text, ex.product_category, ex.deadline, today)
    if clash:
        return "not_a_fit", f"competes with your {clash[0]['category']} exclusivity until {clash[0]['until']}", True

    if model_category:
        return model_category, "model judgement", False

    has_offer = bool(ex.fee_amount or ex.payment_type == "gifting") and bool(ex.deliverables)
    if sig.newsletter and not has_offer:
        return "spam", "bulk newsletter", False
    if has_offer:
        return "deal_offer", "states deliverables and compensation", False
    if _COLLAB_WORDS.search(text):
        return "needs_more_info", "wants to work together but does not give deliverables or budget", False
    return "spam", "no recognisable offer", False


def email_flags(sig, ex, profile, category, model_flags=(), model_rule_hits=()):
    f = []
    if sig.injection:
        f.append(flag("injection_attempt", "critical",
                      "The email contains instructions aimed at an AI assistant. They were ignored and the email "
                      "was not sent to any model."))
    if sig.pay_to_join:
        f.append(flag("pay_to_join", "critical",
                      "Wants you to pay to join or unlock something. Your rule: never pays to join programmes."))
    if sig.personal_data_request:
        f.append(flag("personal_data_request", "critical",
                      "Asks for personal contact or financial details. Never send these to an unverified sender."))
    if sig.impersonates:
        f.append(flag("impersonation", "critical",
                      f"Sent from {sig.sender_domain}, which imitates {signals.DISPLAY[sig.impersonates]} but is not "
                      f"{signals.OFFICIAL[sig.impersonates]}."))
    if signals.phishing(sig):
        f.append(flag("phishing_link", "critical",
                      "Threatens your account and asks you to follow a link. Do not click it; check your "
                      "account directly in the app."))
    if sig.urgency and category in ("scam_or_phishing",):
        f.append(flag("urgency_pressure", "warn", "Uses a short deadline to rush you."))
    for rule in signals.content_rule_hits(sig, profile):
        f.append(flag("content_rule_violation", "critical", f"Breaks your content rule: \"{rule}\""))
    for rule in model_rule_hits:
        if rule not in signals.content_rule_hits(sig, profile):
            f.append(flag("content_rule_violation", "high",
                          f"The model thinks this breaks your rule \"{rule}\". Check it yourself.", source="model"))
    if sig.freemail and category not in ("scam_or_phishing", "spam"):
        f.append(flag("freemail_sender", "info",
                      "Written from a free email address, not a company domain. Common for small brands; "
                      "check that the business exists before sharing details."))
    if ex.mentions_attachment and category not in ("scam_or_phishing", "spam"):
        f.append(flag("attachment_not_visible", "info",
                      "The email mentions an attachment. This tool reads only the message text, so open the "
                      "original email and read it before replying."))
    for m in model_flags:
        f.append(flag("model_note", "info", fmt.clean(m, 100), source="model"))
    return f


def analyse_email(email, profile, client=None):
    sig = signals.detect(email)
    rules_ex = extract.extract_rules(email, profile, sig)
    text = f"{email.get('subject', '')}\n{email.get('body', '')}"
    rules_cat, _, _ = decide_category(sig, rules_ex, profile, text)   # before merge() touches rules_ex

    ex, model_cat, hits, model_flags, source = rules_ex, None, [], [], "rules"
    if client is not None:
        if sig.injection:
            source = "quarantined"                       # hostile text never reaches the model
        else:
            try:
                raw = llm.analyze(client, email, profile)
                m_ex, model_cat, hits, model_flags = llm.coerce(raw, profile)
                ex = merge(m_ex, rules_ex, email, profile)
                source = "llm+rules"
            except (llm.LLMError, ValueError) as e:
                ex.notes.append(f"model unavailable for this email ({e}); used rules only")
                source = "rules (llm failed)"

    category, reason, hard = decide_category(sig, ex, profile, text, model_cat)
    if model_cat and model_cat != category and hard:
        reason += f" (model said {model_cat}; rule overrode it)"

    flags = email_flags(sig, ex, profile, category, model_flags, hits)
    clash = signals.exclusivity_conflicts(profile, ex.brand, text, ex.product_category, ex.deadline,
                                          date.fromisoformat(profile["today"]))
    for c in clash:
        flags.append(flag("exclusivity_conflict", "critical",
                          f"Conflicts with your {c['category']} exclusivity with {c['brand']} until "
                          f"{fmt.day(c['until'])} {c['until'][:4]}. "
                          + (f"This offer's deadline is {fmt.day(ex.deadline)}." if ex.deadline else ""),
                          category=c["category"], until=c["until"]))
    return EmailResult(
        id=email["id"], received_at=email["received_at"], sender=email["from"], subject=email["subject"],
        category=category, category_reason=reason, rules_category=rules_cat, llm_category=model_cat,
        source=source, extraction=ex, flags=flags)


# ---------------------------------------------------------------- deals

_FIELDS = ("deliverables", "fee", "deadline", "usage")


def _merge_terms(results, profile):
    """Fold emails oldest to newest. Newer non-empty values replace older ones."""
    t = {"deliverables": [], "fee_amount": None, "fee_currency": None, "fee_currency_assumed": False,
         "fee_inr": None, "payment_type": None, "product_value_inr": None, "window_start": None,
         "deadline": None, "deadline_text": None, "usage": {"stated": False}, "product_category": None,
         "language": "english"}
    history = []
    for r in results:
        ex, when = r.extraction, r.received_at[:10]
        if ex.fee_inr and t["fee_inr"] and abs(ex.fee_inr - t["fee_inr"]) > 0.5:
            history.append({"field": "fee", "from_inr": t["fee_inr"], "to_inr": ex.fee_inr,
                            "email": r.id, "date": when})
        if ex.deadline and t["deadline"] and ex.deadline != t["deadline"]:
            history.append({"field": "deadline", "from": t["deadline"], "to": ex.deadline, "email": r.id, "date": when})
        if ex.deliverables and t["deliverables"] and ex.deliverables != t["deliverables"]:
            history.append({"field": "deliverables", "from": fmt.deliverables(t["deliverables"]),
                            "to": fmt.deliverables(ex.deliverables), "email": r.id, "date": when})
        if ex.fee_amount:
            t.update(fee_amount=ex.fee_amount, fee_currency=ex.fee_currency,
                     fee_currency_assumed=ex.fee_currency_assumed, fee_inr=ex.fee_inr)
        for k in ("payment_type", "product_value_inr", "window_start", "deadline", "deadline_text",
                  "product_category"):
            if getattr(ex, k):
                t[k] = getattr(ex, k)
        if ex.deliverables:
            t["deliverables"] = ex.deliverables
        if ex.usage.stated:
            t["usage"] = {"stated": True, "months": ex.usage.months, "perpetual": ex.usage.perpetual,
                          "whitelisting": ex.usage.whitelisting, "all_media": ex.usage.all_media}
        if ex.language != "english":
            t["language"] = ex.language
    return t, history


def _missing(terms):
    m = []
    if not terms["deliverables"]:
        m.append("deliverables")
    if not terms["fee_amount"] and terms["payment_type"] != "gifting":
        m.append("fee")
    if not (terms["deadline"] or terms["deadline_text"]):
        m.append("timeline")
    if not terms["usage"].get("stated"):
        m.append("usage")
    return m


_RANK = {"not_a_fit": 0, "deal_offer": 1, "needs_more_info": 2}
_NEGOTIATE = {"below_rate", "usage_rights", "gifting_low_value"}


_NEGOTIATE_WHY = {"below_rate": "the fee is under your rate card",
                  "usage_rights": "the usage rights go beyond your policy",
                  "gifting_low_value": "a product alone is far below your rates"}


def _decide_action(category, codes):
    if category == "not_a_fit":
        return "decline", "It conflicts with your rules or an existing deal."
    if category == "needs_more_info":
        return "ask_for_details", "Not enough information to judge the deal yet."
    if "impossible_deadline" in codes:
        return "ask_for_details", "The deadline has already passed; confirm what they actually need."
    if codes & _NEGOTIATE:
        why = [w for c, w in _NEGOTIATE_WHY.items() if c in codes]
        return "negotiate", "Worth doing, but " + " and ".join(why) + "."
    return "accept", "Terms are within your rates and policy. Get them in writing before you start."


def build_deals(results, profile):
    today = date.fromisoformat(profile["today"])
    members = [r for r in results if r.category in _RANK]
    members.sort(key=lambda r: r.received_at)

    groups = []                                    # list of lists of EmailResult
    for r in members:
        key = _norm(r.extraction.brand) or signals.sender_parts(r.sender)[1]
        for g in groups:
            gk = _norm(g[0].extraction.brand) or signals.sender_parts(g[0].sender)[1]
            gap = (date.fromisoformat(r.received_at[:10]) - date.fromisoformat(g[-1].received_at[:10])).days
            if key == gk and gap <= 45:
                g.append(r)
                break
        else:
            groups.append([r])

    # A follow-up that restates a price but leaves out the details ("same deliverables")
    # is judged on its own as missing info. In the context of its thread it is not.
    for g in groups:
        for idx, r in enumerate(g):
            if r.category == "needs_more_info" and r.extraction.fee_amount \
                    and any(x.category == "deal_offer" for x in g[:idx]):
                r.category = "deal_offer"
                r.category_reason = "follow-up with revised terms on an earlier offer"

    deals = []
    for i, g in enumerate(sorted(groups, key=lambda g: g[0].received_at), 1):
        terms, history = _merge_terms(g, profile)
        category = min((r.category for r in g), key=_RANK.get)
        market = risk.market_value(terms, profile)

        flags = {}
        for r in g:
            for f in r.flags:
                flags.setdefault(f["code"], f)
        for f in risk.deal_flags(terms, history, market, profile, today, category):
            flags[f["code"]] = f
        brand = next((r.extraction.brand for r in reversed(g) if r.extraction.brand), None)
        agency = next((r.extraction.agency for r in reversed(g) if r.extraction.agency), None)
        if agency and brand:
            flags["agency_unverified"] = flag(
                "agency_unverified", "info",
                f"{agency} says it manages this for {brand} but wrote from its own domain. Confirm with {brand} "
                "directly before sending tax or bank details.")
        flags = sorted(flags.values(), key=lambda f: ("critical high warn info".split().index(f["severity"])))

        action, why = _decide_action(category, {f["code"] for f in flags})
        contact = next((r.extraction.contact_name for r in reversed(g) if r.extraction.contact_name), None)
        deal = Deal(
            id=f"D-{i:02d}", brand=brand or "Unknown sender", agency=agency, emails=[r.id for r in g],
            category=category, terms=terms, history=history, flags=flags, market=market, action=action,
            action_reason=why, draft=None, contact_name=contact, contact_email=g[-1].extraction.contact_email,
            first_received=g[0].received_at, last_received=g[-1].received_at)
        deal.draft = drafts.reply(deal, _missing(terms), profile)
        for r in g:
            r.deal_id = deal.id
        deals.append(deal)
    return deals


def classify_junk(results):
    for r in results:
        if r.category == "spam":
            r.junk_action = "ignore"
        elif r.category == "scam_or_phishing":
            r.junk_action = "report"


def run(inbox, profile, client=None):
    results = [analyse_email(e, profile, client) for e in sorted(inbox, key=lambda e: e["id"])]
    classify_junk(results)
    return results, build_deals(results, profile)
