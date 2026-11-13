"""Rule-based extraction. This is both the offline path and the reference the
LLM output is checked against."""
import re
from datetime import date

from . import parsing, signals
from .models import Extraction, Usage

_COUNT = {"a": 1, "an": 1, "one": 1, "ek": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_N = r"(?P<n>\d+|a|an|one|ek|two|three|four|five)"
_IG = r"(?:(?:instagram|insta|ig)\s+)?"
_REEL = re.compile(rf"\b{_N}\s+{_IG}reels?\b", re.I)
_STORY = re.compile(rf"\b{_N}\s+{_IG}(?:stories|story)\b", re.I)
_SHOUT = re.compile(r"\b(?:(?P<n>\d+|a|one)\s+)?(?:youtube\s+)?shout-?outs?\b", re.I)
_DEDICATED = re.compile(r"dedicated\s+(?:youtube\s+)?video", re.I)
_INTEGRATION = re.compile(r"\b(?:(?P<n>\d+)\s+)?integrations?\b", re.I)

_USAGE_MONTHS = re.compile(r"(\d+)\s*months?\b[^.]{0,25}?usage", re.I)
_PERPETUAL = re.compile(r"perpetual|in\s+perpetuity|forever|unlimited\s+usage", re.I)
_WHITELIST = re.compile(r"whitelist|partnership\s+ads?|spark\s+ads?|dark\s+post", re.I)
_ALL_MEDIA = re.compile(r"all\s+media|any\s+media|all\s+channels", re.I)
_GIFT = re.compile(r"\b(free|complimentary|send\s+you|gifted?|gifting|product\s+kit|worth)\b", re.I)
_HINGLISH = re.compile(r"\b(hum|aap|aapke|hain|kya|namaste|dhanyavaad|ji|karna|chahte|saath|hai)\b", re.I)
_AGENCY = re.compile(r"(?i:on\s+behalf\s+of)\s+(?P<b>[A-Z][\w&']*(?:\s+[A-Z][\w&']*){0,3})")
_SIGNOFF = re.compile(r"-\s*(?P<n>[A-Z][a-z]+)(?:,\s*[\w &]+)?\s*$")

_PRODUCT = [("smartphones", r"smartphone|mobile phone"), ("skincare", r"skincare|serum|spf"),
            ("audio", r"earbuds?|earphones?|headphones?"), ("food & beverage", r"coffee|tea brand|cold brew|meal"),
            ("fashion", r"streetwear|apparel|fashion"), ("fitness", r"fitness|gym|workout")]


def _norm(s):
    return re.sub(r"and", "", re.sub(r"[^a-z0-9]", "", s.lower()))


def _stems(domain, local, freemail):
    """Candidate brand stems from the sender address, best first."""
    if freemail:
        return [local.replace(".", "").replace("_", "")]
    labels = domain.split(".")
    labels = labels[:-2] if len(labels) > 2 and labels[-2] in {"co", "com", "org"} else labels[:-1]
    base = labels[-1] if labels else domain
    parts = base.split("-")
    return [base.replace("-", "")] + ([parts[0]] if len(parts) > 1 else [])


def _find_name(stems, text):
    """Find a capitalised phrase in the text that spells one of the stems."""
    tokens = [t[:-2] if t.endswith("'s") else t for t in re.findall(r"[A-Za-z0-9&']+", text)]
    for stem in stems:
        for size in (1, 2, 3):
            for i in range(len(tokens) - size + 1):
                w = tokens[i:i + size]
                if (w[0][0].isupper() or w[0][0].isdigit()) and _norm("".join(w)) == _norm(stem):
                    return " ".join(w)
    return None


def _guess_brand(email, sig, local):
    text = f"{email.get('subject', '')}\n{email.get('body', '')}"
    stems = _stems(sig.sender_domain, local, sig.freemail)
    name = _find_name(stems, text)
    if name:
        return name
    base = stems[0] if stems else ""
    if sig.freemail or not base:
        return None
    return re.sub(r"[-_]+", " ", sig.sender_domain.split(".")[0]).title()


_RETRACTED = re.compile(
    r"\b(original(ly)?|initial(ly)?|previous(ly)?|earlier|was)\b", re.I)
_REVISED_ACTIVE = re.compile(
    r"\b(now|can\s+(now\s+)?(do|offer|pay)|increase(d)?\s+(this\s+)?to|revised\s+(internally\s+)?to|bump(ed)?\s+to|final(ly)?|new\s+budget|offer\s+is|budget\s+is)\b", re.I)


def _select_fee(candidates):
    """Select the amount most semantically associated with the current/final offer."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    best_cand = candidates[0][0]
    best_score = -1

    for a, sent, prev_window in candidates:
        score = 0
        is_retracted = bool(_RETRACTED.search(prev_window))
        is_active = bool(_REVISED_ACTIVE.search(prev_window))

        if is_active:
            score += 2
        if is_retracted:
            score -= 2

        if score > best_score:
            best_score = score
            best_cand = a

    return best_cand


def _deliverables(text):
    out = []

    def add(platform, kind, count):
        out.append({"platform": platform, "type": kind, "count": count,
                    "rate_key": f"{platform}_{kind}" if kind != "shoutout" else None})

    n = lambda m: _COUNT.get((m.group("n") or "1").lower()) or int(m.group("n"))
    for rx, kind in ((_REEL, "reel"), (_STORY, "story")):
        m = rx.search(text)
        if m:
            add("instagram", kind, n(m))
    m = _SHOUT.search(text)
    if m:
        add("youtube", "shoutout", n(m) if m.group("n") else 1)
    if re.search(r"youtube", text, re.I):
        if _DEDICATED.search(text):
            add("youtube", "dedicated_video", 1)
        elif _INTEGRATION.search(text):
            m = _INTEGRATION.search(text)
            add("youtube", "integration", int(m.group("n") or 1))
    return out


def _usage(text):
    u = Usage()
    m = _USAGE_MONTHS.search(text)
    if m:
        u.months = int(m.group(1))
    u.perpetual = bool(_PERPETUAL.search(text))
    u.whitelisting = bool(_WHITELIST.search(text))
    u.all_media = bool(_ALL_MEDIA.search(text))
    u.stated = bool(u.months or u.perpetual or u.whitelisting or u.all_media)
    return u


def extract_rules(email, profile, sig):
    body = email.get("body", "")
    text = f"{email.get('subject', '')}\n{body}"
    local, _ = signals.sender_parts(email.get("from"))
    received = date.fromisoformat(email["received_at"][:10])
    ex = Extraction(contact_email=email.get("from"))

    # Agency mail names the real brand: "On behalf of Dew Lab".
    m = _AGENCY.search(text)
    if m:
        ex.brand = m.group("b").strip()
        ex.agency = _guess_brand(email, sig, local)
    else:
        ex.brand = _guess_brand(email, sig, local)

    m = _SIGNOFF.search(body.strip())
    ex.contact_name = m.group("n") if m else None
    ex.language = "hinglish" if len(_HINGLISH.findall(body)) >= 2 else "english"
    ex.deliverables = _deliverables(text)
    ex.usage = _usage(text)
    ex.mentions_attachment = sig.mentions_attachment
    ex.window_start, ex.deadline, ex.deadline_text = parsing.find_dates(text, received)

    candidates = []
    for a in parsing.find_amounts(body):
        before = body[max(0, a.start - 12):a.start].lower()
        if re.search(r"worth( of)?\s*$", before):
            ex.product_value_inr = parsing.to_inr(a.value, a.currency, parsing.usd_rate(profile))
            continue
        sent = parsing.sentence_at(body, a.start)
        if signals._PAY_TO_JOIN.search(sent):
            ex.notes.append(f"asks the creator to pay {a.value:,.0f}")
            continue
        prev_window = body[max(0, a.start - 60):a.start].lower()
        candidates.append((a, sent, prev_window))

    fee = _select_fee(candidates)
    if fee:
        ex.fee_amount, ex.fee_currency, ex.fee_currency_assumed = fee.value, fee.currency, fee.assumed
        ex.fee_inr = parsing.to_inr(fee.value, fee.currency, parsing.usd_rate(profile))
        ex.payment_type = "cash"
    elif ex.product_value_inr or _GIFT.search(body):
        ex.payment_type = "gifting"

    for label, pattern in _PRODUCT:
        if re.search(pattern, text, re.I):
            ex.product_category = label
            break
    return ex
