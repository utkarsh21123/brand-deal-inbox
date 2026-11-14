"""Deterministic checks on a single email.

These run before and independently of any model. They cover the things that
must not depend on a model's mood: hostile instructions, payment demands,
look-alike domains, and the creator's hard rules.
"""
import re
from dataclasses import dataclass, field
from datetime import date

FREEMAIL = {"gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com", "proton.me", "rediffmail.com"}
OFFICIAL = {"youtube": "youtube.com", "google": "google.com", "instagram": "instagram.com",
            "facebook": "facebook.com", "meta": "meta.com"}
DISPLAY = {"youtube": "YouTube", "google": "Google", "instagram": "Instagram", "facebook": "Facebook", "meta": "Meta"}

_INJECTION = re.compile(
    r"(?:note|message|instruction|attention)s?\s+(?:to|for)\s+(?:any\s+|the\s+)?(?:ai(?:\s+assistant|\s+agent|\s+model)?|llm|language\s+model|bot|virtual\s+assistant|automated\s+assistant|(?:assistant|agent|model)\s+(?:processing|reading|evaluating|triaging|handling)\s+(?:this|the|an?)\s+(?:inbox|email|message))"
    r"|(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system)\s+(?:instructions|rules|directives|prompts|system\s+prompt)(?:\s+above)?"
    r"|(?:bypass|override|reset)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:(?:previous|prior|above|earlier|system)\s+)?(?:instructions|directives|prompts|system\s+prompt)(?:\s+above)?"
    r"|(?:bypass|override|reset)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system)\s+rules(?:\s+above)?"
    r"|(?:ignore|disregard|forget)\s+(?:the\s+|your\s+)?(?:instructions|rules|directives|prompts)\s+above"
    r"|\bfollow\s+(?:these\s+|the\s+)?new\s+instructions\s+instead\b"
    r"|(?:previous|prior|system)\s+instructions\s+and\s+follow\s+(?:these\s+|the\s+)?new\s+instructions"
    r"|\byou are\s+(?:now\s+)?(?:an?\s+)?(?:ai|assistant|language model|bot)[;,.]?\s*(?:follow|please)"
    r"|(?:reveal|expose|leak|show|output|print|provide|give)\s+(?:me\s+)?(?:the\s+|all\s+|your\s+)?(?:system\s+instructions|system\s+prompt|hidden\s+instructions|developer\s+prompt)"
    r"|\b(?:reveal|expose|leak|output|print)\s+(?:the\s+|all\s+|creator(?:'s)?\s+)?(?:private|confidential)\s+information\s+(?:and|regarding|about|including)\s+(?:creator\s+)?(?:bank|home|phone|personal)"
    r"|(?:classify|label|mark|categori[sz]e)\s+this\s+(?:email|message)?\s*as\s+(?:a\s+)?(?:deal_offer|deal|accept|safe|verified|not_a_fit|spam|valid|legit)\b"
    r"|\b(?:you are|act|pretend to be|roleplay|operating)\s+as\s+(?:an?\s+)?(?:ai|assistant|language model|bot)\b"
    r"|\byou are now an?\s+(?:ai|assistant|language model|bot)\b"
    r"|\bsystem\s+prompt\s*:"
    r"|\b(?:ignore|reveal|show|output|leak|reset|override|bypass|forget|change)\s+(?:the\s+|your\s+)?system\s+prompt\b"
    r"|\byou\s+must\s+(?:now\s+)?(?:recommend|reply|respond)\s+(?:with\s+|that\s+|saying\s+)?(?:accept|deal_offer|confirming\s+a\s+fee|positive)\b"
    r"|recommend\s+accept,\s+and\s+draft\s+a\s+reply",
    re.I)
_PAY_TO_JOIN = re.compile(
    r"\b(?:registration|joining|membership|activation|processing|enrol\w*|onboarding|verification)\s+fee\b"
    r"|\b(?:you|creator|influencer|applicant)\s+(?:must\s+|need\s+to\s+|have\s+to\s+|to\s+)?pay\s+(?:a|an|the)?\s*(?:one[- ]time\s+)?(?:\w+\s+){0,2}fee\b"
    r"|\bpay\s+(?:a|an|the)?\s*(?:one[- ]time\s+)?(?:\w+\s+){0,2}fee(?:\s+of\s+[^.\n]{1,20})?\s+to\s+(?:join|unlock|participate|enrol|register|access|work|collaborate)\b"
    r"|\b(?:you|creator|influencer)\s+(?:must\s+|need\s+to\s+|to\s+)?(?:pay|deposit|transfer|send)\s+(?:a\s+)?(?:security|refundable)\s+deposit\b"
    r"|\b(?:pay|send|transfer|submit)\s+(?:a\s+)?(?:security|refundable)\s+deposit\s+(?:to\s+(?:join|unlock|receive|start|participate)|of\s+(?:rs|inr|\$|₹|\d))\b"
    r"|\b(?:security|refundable)\s+deposit\s+(?:is\s+)?(?:required|needed|to\s+join|to\s+unlock|to\s+receive)\b",
    re.I)
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
        if ex.get("until") and date.fromisoformat(ex["until"]) < today:
            continue
        if window_end and window_end > ex["until"]:
            continue
        out.append(ex)
    return out
