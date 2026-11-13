"""The model layer, tested with stand-ins. These tests do not call a real model."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dealdesk import llm, pipeline


class Stub:
    """Stands in for the model. Returns one canned reply, and fails if called with nothing to return."""
    def __init__(self, reply=None):
        self.reply, self.seen = reply, []

    def complete_json(self, system, user):
        self.seen.append(user)
        if self.reply is None:
            raise AssertionError("the model should not have been called")
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def one(email_id, inbox, profile, reply):
    stub = Stub(reply)
    return pipeline.analyse_email(inbox[email_id], profile, stub), stub


def test_injection_email_never_reaches_the_model(inbox, profile):
    stub = Stub()                                             # raises if called
    r = pipeline.analyse_email(inbox["E-07"], profile, stub)
    assert r.source == "quarantined" and r.category == "scam_or_phishing"
    assert stub.seen == []


def test_rules_override_a_model_that_falls_for_a_scam(inbox, profile):
    reply = {"category": "deal_offer", "brand": "Glowstar", "fee_amount": 20000, "fee_currency": "INR",
             "deliverables": [{"platform": "instagram", "type": "reel", "count": 1}]}
    r, _ = one("E-03", inbox, profile, reply)
    assert r.category == "scam_or_phishing"
    assert r.llm_category == "deal_offer" and "rule overrode" in r.category_reason


def test_hallucinated_fee_is_dropped(inbox, profile):
    reply = {"category": "deal_offer", "brand": "Urban Thread", "fee_amount": 90000, "fee_currency": "INR"}
    r, _ = one("E-08", inbox, profile, reply)
    assert r.extraction.fee_amount is None
    assert any("not in the email" in n for n in r.extraction.notes)


def test_invented_brand_is_dropped(inbox, profile):
    r, _ = one("E-08", inbox, profile, {"category": "needs_more_info", "brand": "Totally Different Corp"})
    assert r.extraction.brand == "Urban Thread"


def test_bad_json_falls_back_to_rules(inbox, profile):
    r, _ = one("E-05", inbox, profile, ValueError("not json"))
    assert r.source == "rules (llm failed)" and r.category == "not_a_fit"


def test_model_can_add_what_rules_miss(profile):
    email = {"id": "X-1", "received_at": "2026-11-10 10:00", "from": "chai@masalacup.in", "subject": "सहयोग",
             "body": "नमस्ते रिया, हम एक चाय ब्रांड हैं। हम आपके साथ 1 रील करना चाहते हैं। बजट 30000 रुपये है।"}
    reply = {"category": "deal_offer", "brand": None, "fee_amount": 30000, "fee_currency": "INR",
             "deliverables": [{"platform": "instagram", "type": "reel", "count": 1}]}
    rules_only = pipeline.analyse_email(email, profile, None)
    with_model = pipeline.analyse_email(email, profile, Stub(reply))
    assert rules_only.category == "spam"
    assert with_model.category == "deal_offer" and with_model.extraction.fee_inr == 30000


def test_model_cannot_invent_a_content_rule(profile):
    raw = {"category": "deal_offer", "content_rule_violations": ["No selling shoes", "No crypto or trading-tip promotions."]}
    _, _, hits, _ = llm.coerce(raw, profile)
    assert hits == ["No crypto or trading-tip promotions."]


def test_coerce_tolerates_garbage(profile):
    ex, cat, hits, flags = llm.coerce({"category": "nonsense", "fee_amount": "lots", "deliverables": "x",
                                       "usage_rights": 5, "deadline": "tomorrow"}, profile)
    assert cat is None and ex.fee_amount is None and ex.deliverables == [] and ex.deadline is None


def test_parse_json_handles_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        llm.parse_json("[1]")


class _Handler(BaseHTTPRequestHandler):
    hits = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.hits.append((self.path, self.headers.get("Authorization"), body))
        out = {"choices": [{"message": {"content": '```json\n{"category": "spam"}\n```'}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_client_talks_to_an_openai_compatible_server_and_caches(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = llm.Client("test", "m", f"http://127.0.0.1:{srv.server_port}/v1", "k", cache_dir=tmp_path)
        assert c.complete_json("sys", "user") == {"category": "spam"}
        assert c.complete_json("sys", "user") == {"category": "spam"}     # second call is cached
    finally:
        srv.shutdown()
    path, auth, body = _Handler.hits[0]
    assert path == "/v1/chat/completions" and auth == "Bearer k"
    assert body["temperature"] == 0 and body["messages"][0]["role"] == "system"
    assert len(_Handler.hits) == 1 and c.cache_hits == 1


class _Retry429Handler(BaseHTTPRequestHandler):
    requests = 0

    def do_POST(self):
        _Retry429Handler.requests += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if _Retry429Handler.requests == 1:
            self.send_response(429)
            self.send_header("Retry-After", "0.01")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        out = {"choices": [{"message": {"content": json.dumps({"category": "deal_offer"})}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_client_retries_on_429_and_succeeds(tmp_path):
    _Retry429Handler.requests = 0
    srv = HTTPServer(("127.0.0.1", 0), _Retry429Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = llm.Client("test", "m", f"http://127.0.0.1:{srv.server_port}/v1", "k", cache_dir=tmp_path)
        res = c.complete_json("sys", "user")
        assert res == {"category": "deal_offer"}
        assert _Retry429Handler.requests == 2
        assert c.calls == 2
    finally:
        srv.shutdown()


def test_prompt_wraps_email_and_withholds_nothing_secret(inbox, profile):
    p = llm.build_user(inbox["E-07"], profile)
    assert "<email>" in p and "</email>" in p
    assert "riya.creates@example.com" not in p       # creator's own address is not sent
