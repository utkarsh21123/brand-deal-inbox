"""Score a run against data/expected.json."""
import re

CHECKED = ("brand", "fee_inr", "payment_type", "deadline", "deliverables", "usage_months", "usage_perpetual")


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _actual(r, field):
    ex = r.extraction
    if field == "brand":
        return ex.brand
    if field == "fee_inr":
        return round(ex.fee_inr) if ex.fee_inr else None
    if field == "payment_type":
        return ex.payment_type
    if field == "deadline":
        return ex.deadline
    if field == "deliverables":
        out = {}
        for d in ex.deliverables:
            if d.get("rate_key"):
                out[d["rate_key"]] = out.get(d["rate_key"], 0) + d["count"]
        return out
    if field == "usage_months":
        return ex.usage.months
    if field == "usage_perpetual":
        return ex.usage.perpetual


def _same(field, want, got):
    if field == "brand":
        return _norm(want) == _norm(got)
    return want == got


def score(expected, results, deals):
    by_id = {r.id: r for r in results}
    rep = {"category": [], "strict": 0, "lenient": 0, "fields": [], "deals": [], "flags": [], "actions": [],
           "disagreements": []}

    for eid, exp in expected["emails"].items():
        r = by_id[eid]
        ok = r.category == exp["category"]
        alt = ok or r.category in exp.get("also_acceptable", [])
        rep["strict"] += ok
        rep["lenient"] += alt
        rep["category"].append((eid, exp["category"], r.category, ok, alt))
        if r.llm_category and r.llm_category != r.rules_category:
            rep["disagreements"].append((eid, r.rules_category, r.llm_category, r.category))
        for f in CHECKED:
            if f in exp:
                got = _actual(r, f)
                rep["fields"].append((eid, f, exp[f], got, _same(f, exp[f], got)))

    deal_of = {e: d for d in deals for e in d.emails}
    for ed in expected.get("deals", []):
        found = deal_of.get(ed["emails"][0])
        grouped = found is not None and set(found.emails) == set(ed["emails"])
        rep["deals"].append((ed["brand"], sorted(ed["emails"]), sorted(found.emails) if found else None, grouped))
        if found is None:
            continue
        if "fee_inr" in ed:
            got = round(found.terms["fee_inr"]) if found.terms["fee_inr"] else None
            rep["fields"].append((ed["brand"], "latest fee_inr", ed["fee_inr"], got, got == ed["fee_inr"]))
        rep["actions"].append((ed["brand"], ed["action"], found.action, found.action == ed["action"]))
        have = {f["code"] for f in found.flags}
        for c in ed.get("must_flag", []):
            rep["flags"].append((ed["brand"], c, "present", c in have, True))
        for c in ed.get("must_not_flag", []):
            rep["flags"].append((ed["brand"], c, "absent", c not in have, False))

    for eid, ej in expected.get("junk", {}).items():
        r = by_id[eid]
        rep["actions"].append((eid, ej["action"], r.junk_action, r.junk_action == ej["action"]))
        have = {f["code"] for f in r.flags}
        for c in ej.get("must_flag", []):
            rep["flags"].append((eid, c, "present", c in have, True))
    return rep


def _frac(items, idx):
    ok = sum(1 for i in items if i[idx])
    return f"{ok}/{len(items)}"


def render(rep, mode):
    n = len(rep["category"])
    lines = [f"# Evaluation ({mode})", "",
             "| Check | Result |", "|---|---|",
             f"| Category, strict | {rep['strict']}/{n} |",
             f"| Category, lenient (accepts listed alternatives) | {rep['lenient']}/{n} |",
             f"| Extracted fields | {_frac(rep['fields'], 4)} |",
             f"| Deals grouped as expected | {_frac(rep['deals'], 3)} |",
             f"| Recommended action | {_frac(rep['actions'], 3)} |",
             f"| Risk flags (must be present / must be absent) | {_frac(rep['flags'], 3)} |", ""]
    misses = []
    for eid, want, got, ok, alt in rep["category"]:
        if not ok:
            misses.append(f"- {eid}: category expected `{want}`, got `{got}`" + (" (accepted as an alternative)" if alt else ""))
    for who, f, want, got, ok in rep["fields"]:
        if not ok:
            misses.append(f"- {who}: {f} expected {want!r}, got {got!r}")
    for brand, want, got, ok in rep["deals"]:
        if not ok:
            misses.append(f"- group {brand}: expected {want}, got {got}")
    for who, want, got, ok in rep["actions"]:
        if not ok:
            misses.append(f"- {who}: action expected `{want}`, got `{got}`")
    for who, code, kind, ok, _ in rep["flags"]:
        if not ok:
            misses.append(f"- {who}: flag `{code}` should be {kind}")
    lines += ["## Misses", ""] + (misses or ["None."])
    if rep["disagreements"]:
        lines += ["", "## Model and rules disagreed", ""]
        lines += [f"- {e}: rules said `{r}`, model said `{m}`, final `{f}`" for e, r, m, f in rep["disagreements"]]
    return "\n".join(lines) + "\n"
