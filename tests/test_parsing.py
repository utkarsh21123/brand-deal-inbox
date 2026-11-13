from datetime import date

from dealdesk import fmt, parsing


def values(text):
    return [(a.value, a.currency, a.assumed) for a in parsing.find_amounts(text)]


def test_indian_grouping():
    assert fmt.inr(120000) == "₹1,20,000"
    assert fmt.inr(3500) == "₹3,500"
    assert fmt.inr(1000000) == "₹10,00,000"
    assert fmt.inr(999) == "₹999"


def test_amount_formats():
    assert values("INR 1,20,000 all-inclusive") == [(120000, "INR", False)]
    assert values("We'll pay Rs 3,00,000 for 2 reels") == [(300000, "INR", False)]
    assert values("USD 1,200. Video") == [(1200, "USD", False)]
    assert values("Rs 1.5 lakh") == [(150000, "INR", False)]
    assert values("INR 1,00,000, 3 months") == [(100000, "INR", False)]


def test_bare_k_is_assumed_rupees():
    assert values("Budget 25k hai") == [(25000, "INR", True)]


def test_no_false_positive_on_words_ending_in_rs():
    assert values("our users 5 times more") == []


def test_dates():
    ref = date(2026, 11, 3)
    assert parsing.find_dates("between 15 and 25 November", ref) == ("2026-11-15", "2026-11-25", None)
    assert parsing.find_dates("before 10 December", ref) == (None, "2026-12-10", None)
    assert parsing.find_dates("within 2 weeks of delivery", ref)[2] == "within 2 weeks of delivery"


def test_year_rolls_forward_for_early_months():
    assert parsing.find_dates("by 10 February", date(2026, 11, 10))[1] == "2027-02-10"


def test_past_date_in_same_year_stays_past():
    assert parsing.find_dates("by 1 November", date(2026, 11, 10))[1] == "2026-11-01"


def test_usd_rate_from_profile(profile):
    assert parsing.usd_rate(profile) == 84


def test_clean_strips_markup():
    out = fmt.clean("[click](http://x)\n# Hi `x`")
    assert not any(ch in out for ch in "[]#`\n")
