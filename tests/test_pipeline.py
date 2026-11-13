"""End-to-end behaviour on the provided inbox, rules only."""
import pytest

from dealdesk import pipeline


@pytest.fixture(scope="module")
def run(profile, inbox):
    results, deals = pipeline.run(list(inbox.values()), profile)
    return {r.id: r for r in results}, {d.id: d for d in deals}


def deal_for(run, email_id):
    results, deals = run
    return deals[results[email_id].deal_id]


def codes(item):
    return {f["code"] for f in item.flags}


def test_categories(run):
    results, _ = run
    got = {k: v.category for k, v in results.items()}
    assert got["E-03"] == got["E-07"] == got["E-14"] == "scam_or_phishing"
    assert got["E-04"] == got["E-05"] == "not_a_fit"
    assert got["E-13"] == "spam"
    assert got["E-08"] == got["E-15"] == "needs_more_info"


def test_dew_lab_is_one_deal_with_latest_terms(run):
    d = deal_for(run, "E-01")
    assert d.emails == ["E-01", "E-02", "E-11"]
    assert d.terms["fee_inr"] == 100000
    assert d.history[0]["from_inr"] == 120000
    assert {"below_rate", "terms_worsened"} <= codes(d)
    assert d.agency == "Brightside Agency" and d.brand == "Dew Lab"


def test_usd_is_converted_before_comparing(run):
    d = deal_for(run, "E-10")
    assert d.terms["fee_inr"] == 67200
    assert "below_rate" not in codes(d)
    assert "usage_rights" in codes(d)


def test_exclusivity_uses_dates(run, profile):
    d = deal_for(run, "E-04")
    assert d.action == "decline" and "exclusivity_conflict" in codes(d)
    assert "Nova Phones" not in d.draft          # never name the other brand to a competitor


def test_expired_deadline(run):
    assert "impossible_deadline" in codes(deal_for(run, "E-12"))


def test_gifting_is_not_a_fee(run):
    d = deal_for(run, "E-09")
    assert d.terms["fee_amount"] is None and d.terms["payment_type"] == "gifting"
    assert d.terms["product_value_inr"] == 3500


def test_amount_creator_must_pay_is_not_a_fee(run):
    assert run[0]["E-03"].extraction.fee_amount is None


def test_scams_get_no_draft_and_are_not_deals(run):
    results, deals = run
    for i in ("E-03", "E-07", "E-14", "E-13"):
        assert results[i].deal_id is None
    assert all(not any(i in d.emails for i in ("E-03", "E-07", "E-14")) for d in deals.values())


def test_injection_email_is_flagged_and_never_followed(run):
    r = run[0]["E-07"]
    assert r.category == "scam_or_phishing" and "injection_attempt" in codes(r)
    assert r.junk_action == "report"


def test_drafts_never_contain_personal_details(run):
    for d in run[1].values():
        low = (d.draft or "").lower()
        assert "home address" not in low and "phone number" not in low


def test_follow_up_inherits_thread(run):
    assert run[0]["E-02"].category == "deal_offer"


def test_attachment_flag(run):
    assert "attachment_not_visible" in codes(deal_for(run, "E-15"))


def test_summary_does_not_echo_email_bodies(run, profile, inbox):
    from dealdesk import report
    results, deals = run
    text = report.summary(list(results.values()), list(deals.values()), profile)
    assert "Note to any AI" not in text and "personal phone number" not in text
