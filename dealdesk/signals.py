"""Deterministic checks on a single email.

These run before and independently of any model. They cover the things that
must not depend on a model's mood: hostile instructions, payment demands,
look-alike domains, and the creator's hard rules.
"""
import re
from dataclasses import dataclass, field

FREEMAIL = {"gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com", "proton.me", "rediffmail.com"}
OFFICIAL = {"youtube": "youtube.com", "google": "google.com", "instagram": "instagram.com",
            "facebook": "facebook.com", "meta": "meta.com"}
DISPLAY = {"youtube": "YouTube", "google": "Google", "instagram": "Instagram", "facebook": "Facebook", "meta": "Meta"}

_INJECTION = re.compile(
    r"(note|message|instruction|attention)s?\s+(to|for)\s+(any\s+|the\s+)?(ai|assistant|llm|model|bot|agent)"
    r"|(ignore|disregard|forget|bypass|override|reset)\s+(all\s+|any\s+|the\s+)?(?:(previous|prior|above|earlier|system)\s+)?(instructions|rules|directives|prompts)(?:\s+above)?"
    r"|follow\s+(these\s+|the\s+)?new\s+instructions"
    r"|(reveal|expose|leak|show|output|print|provide)\s+(the\s+|all\s+)?(system\s+instructions|system\s+prompt|hidden\s+instructions|private\s+information|confidential\s+information)"
    r"|(classify|label|mark|categori[sz]e)\s+this\s+(email|message)?\s*as"
    r"|\bas an? (ai|assistant|language model)\b"
    r"|system\s+prompt|you\s+must\s+(now\s+)?(recommend|reply|respond)",
    re.I)
_PAY_TO_JOIN = re.compile(
    r"\b(registration|joining|membership|activation|processing|enrol\w*|onboarding|verification)\s+fee\b"
    r"|\bpay\s+(?:a|an|the)?\s*(?:one[- ]time\s+)?(?:\w+\s+){0,2}fee\b"
    r"|\b(security|refundable)\s+deposit\b", re.I)
_PERSONAL_DATA = re.compile(
    r"home\s+address|personal\s+phone|phone\s+number|bank\s+(account|details)|\botp\b|password"
    r"|aadhaar|\bpan\s+(card|number)|card\s+number|\bcvv\b", re.I)
_ACCOUNT_THREAT = re.compile(
    r"suspend|terminat|copyright\s+strike|verify\s+your\s+account|account\s+(will\s+be\s+)?(locked|closed|disabled)", re.I)
_URGENCY = re.compile(
    r"\b\d+\s+hours?\b|\burgent(ly)?\b|\bimmediately\b|\bact\s+now\b|\bexpires?\b|\blast\s+chance\b"
    r"|\bvalid\s+for\b|\bonly\s+today\b", re.I)
_URL = re.compile(r"https?://([^\s/]+)\S*", re.I)
_NEWSLETTER = re.compile(r"unsubscribe|view\s+in\s+browser|you\s+are\s+receiving\s+this", re.I)

_GAMBLING = re.compile(
    r"\bfantasy\b|\bbett?ing\b|\bbet\b|casino|poker|rummy|teen\s*patti|gambl|satta|lottery|real[- ]money\s+gam", re.I)
_CRYPTO = re.compile(
    r"crypto|bitcoin|ethereum|\bnfts?\b|forex|trading\s+(tips?|signals?)|stock\s+tips?|binary\s+options", re.I)

# Words that identify a product category, keyed by the stem of the category
# name in the creator profile. Unknown categories fall back to the stem itself.
_CATEGORY_WORDS = {
    "smartphone": ["smartphone", "smart phone", "mobile phone", "android phone", "flagship phone"],
    "earbud": ["earbud", "earphone", "headphone", "tws"],
    "skincare": ["skincare", "serum", "sunscreen", "spf", "moisturi"],
}


@dataclass
class Signals:
    sender: str = ""
    sender_domain: str = ""
    freemail: bool = False
    injection: list = field(default_factory=list)
    pay_to_join: bool = False
    personal_data_request: bool = False
    account_threat: bool = False
    impersonates: str = ""
    link_domains: list = field(default_factory=list)
    urgency: bool = False
    newsletter: bool = False
    gambling: bool = False
    crypto: bool = False
    mentions_attachment: bool = False


def sender_parts(raw):
    m = re.search(r"([\w.+-]+)@([\w.-]+)", raw or "")
    return (m.group(1).lower(), m.group(2).lower()) if m else ("", "")


def detect(email):
    text = f"{email.get('subject', '')}\n{email.get('body', '')}"
    local, domain = sender_parts(email.get("from"))
    s = Signals(sender=email.get("from", ""), sender_domain=domain, freemail=domain in FREEMAIL)

    s.injection = [m.group(0) for m in _INJECTION.finditer(text)][:3]
    s.pay_to_join = bool(_PAY_TO_JOIN.search(text))
    s.personal_data_request = bool(_PERSONAL_DATA.search(text))
    s.account_threat = bool(_ACCOUNT_THREAT.search(text))
    s.urgency = bool(_URGENCY.search(text))
    s.link_domains = sorted({m.group(1).lower() for m in _URL.finditer(text)})
    s.newsletter = bool(_NEWSLETTER.search(text)) or local in {"newsletter", "no-reply", "noreply"}
    s.gambling = bool(_GAMBLING.search(text))
    s.crypto = bool(_CRYPTO.search(text))
    s.mentions_attachment = bool(re.search(r"\battach(ed|ment)\b", text, re.I))

    for word, official in OFFICIAL.items():
        if word in domain and domain != official and not domain.endswith("." + official):
            s.impersonates = word
    return s


def phishing(s):
    """Account-threat language plus a link or a platform look-alike sender."""
    return s.account_threat and (bool(s.link_domains) or bool(s.impersonates))


def content_rule_hits(s, profile):
    """Which of the creator's written rules the keyword detectors can prove.

    The profile rules are free text, so this maps the ones we recognise onto
    detectors. A model can judge rules we have no detector for (see llm.py),
    but only this function is allowed to force a category.
    """
    hits = []
    for rule in profile.get("content_rules", []):
        low = rule.lower()
        if (("gambling" in low or "betting" in low or "fantasy" in low) and (s.gambling)) \
                or (("crypto" in low or "trading" in low) and s.crypto) \
                or ("pays to join" in low or "pay to join" in low) and s.pay_to_join:
            hits.append(rule)
    return hits


def _norm(s):
    return re.sub(r"and", "", re.sub(r"[^a-z0-9]", "", s.lower()))


def exclusivity_conflicts(profile, brand, text, product_category, window_end, today):
    """Exclusivity entries that this offer would break.

    A conflict needs a category match against a different brand, and content
    that would land before the exclusivity ends. With no deadline we assume it
    would, because that is the cautious reading.
    """
    out = []
    hay = f"{text} {product_category or ''}".lower()
    for ex in profile.get("current_exclusivity", []):
        if brand and _norm(brand) == _norm(ex["brand"]):
            continue
        stem = re.sub(r"s$", "", ex["category"].lower())
        words = _CATEGORY_WORDS.get(stem, [stem])
        if not any(w in hay for w in words):
            continue
        if window_end and window_end > ex["until"]:
            continue
        out.append(ex)
    return out
