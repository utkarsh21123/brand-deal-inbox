from dataclasses import dataclass, field, asdict

CATEGORIES = ("deal_offer", "needs_more_info", "not_a_fit", "scam_or_phishing", "spam")
SEVERITY_ORDER = {"critical": 0, "high": 1, "warn": 2, "info": 3}


def flag(code, severity, message, source="rules", **data):
    out = {"code": code, "severity": severity, "message": message, "source": source}
    if data:
        out["data"] = data
    return out


@dataclass
class Usage:
    stated: bool = False
    months: int = None
    perpetual: bool = False
    whitelisting: bool = False
    all_media: bool = False


@dataclass
class Extraction:
    """Facts one email states. Missing means the email does not say, not "zero"."""
    brand: str = None
    agency: str = None
    contact_name: str = None
    contact_email: str = None
    language: str = "english"
    deliverables: list = field(default_factory=list)   # {platform, type, count, rate_key}
    fee_amount: float = None
    fee_currency: str = None
    fee_currency_assumed: bool = False
    fee_inr: float = None
    payment_type: str = None                            # cash | gifting | mixed
    product_value_inr: float = None
    window_start: str = None
    deadline: str = None
    deadline_text: str = None
    usage: Usage = field(default_factory=Usage)
    product_category: str = None
    mentions_attachment: bool = False
    notes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class EmailResult:
    id: str
    received_at: str
    sender: str
    subject: str
    category: str
    category_reason: str
    rules_category: str
    llm_category: str = None
    source: str = "rules"            # rules | llm+rules | quarantined | rules (llm failed)
    extraction: Extraction = field(default_factory=Extraction)
    flags: list = field(default_factory=list)
    deal_id: str = None
    junk_action: str = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Deal:
    id: str
    brand: str
    agency: str
    emails: list
    category: str
    terms: dict
    history: list
    flags: list
    market: dict
    action: str
    action_reason: str
    draft: str
    contact_name: str = None
    contact_email: str = None
    first_received: str = ""
    last_received: str = ""

    def to_dict(self):
        return asdict(self)
