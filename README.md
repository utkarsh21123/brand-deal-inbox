# dealdesk

A command-line tool that reads a creator's brand-deal inbox and says, for each email, what it is, what the deal actually says, what is risky, and what to do next. Written for the JEEVIT Founding AI Engineer task.

It runs with no API key and no installed packages (Python 3.10+, standard library only). A language model is optional; when one is configured it handles the messy reading, and plain code still makes the decisions that have to be right.

## Run it

```bash
git clone https://github.com/utkarsh21123/brand-deal-inbox.git && cd brand-deal-inbox
```

### macOS / Linux

```bash
python3 -m dealdesk run            # processes data/inbox.json, writes ./out
python3 -m dealdesk eval           # scores the run against data/expected.json
python3 -m pytest                  # unit tests (needs: pip install pytest)
```

### Windows (PowerShell / Command Prompt)

```bash
python -m dealdesk run             # processes data/inbox.json, writes ./out
python -m dealdesk eval            # scores the run against data/expected.json
python -m pytest                   # unit tests (needs: pip install pytest)
```

With no `.env` this runs in rules-only mode. To add a model, copy `.env.example` to `.env`, set `LLM_PROVIDER` (`groq`, `gemini`, `openrouter` or `ollama`) and `LLM_API_KEY`, then run the same commands. `--mode rules` forces no model even if one is configured; `--mode llm` refuses to run without one.

Output goes to `out/`:

| File | What it is |
|---|---|
| `summary.md` | The page the creator reads: what needs attention today, this week, what to decline, what to report |
| `drafts.md` | Draft replies, one per deal that needs one. Nothing is ever sent |
| `deals.json` | Deals with merged terms, change history, risk flags, recommended action, draft |
| `emails.json` | Per-email category, reason, extracted fields, flags |

`sample_output/` has a committed rules-only run, so you can read the result without running anything.

## What the tool decides

For each email: one of the five categories, with a one-line reason. For real brands: brand, agency, contact, deliverables, fee and currency (also in INR at the profile's rate), cash or gifting, deadline, usage rights. Emails about the same deal are grouped and the latest terms win, with a history of what changed. Risk flags are checked against the profile, each with a reason in plain language. Each deal gets one of accept, negotiate, ask for details, decline, and a draft reply where a reply makes sense. Scams are reported and get no draft. Newsletters are ignored.

## Design

The split I aimed for: the model reads, code decides.

| Step | Done by | Why |
|---|---|---|
| Injection, pay-to-join, phishing and personal-data detection | Code | A scam check that depends on a model's mood is not a safety check. These run first and can force a category |
| Amount parsing (`1,20,000`, `3 lakh`, `25k`, USD to INR) | Code | Must be exact. A wrong digit is a wrong deal |
| Dates, deadlines, "is this in the past" | Code | Same reason, and the model does not know today's date unless told |
| Content rules and exclusivity | Code (keyword detectors plus date logic) | Hard rules. A model may flag extra rule breaks but only the detectors can force a category |
| Reading free text: brand, deliverables, fee, usage, language | Model, with a rules fallback | Real emails do not follow patterns. This is where regexes stop scaling |
| Soft classification (deal, needs info, spam) | Model, with a rules fallback | Judgement calls on messy text |
| Grouping emails into deals | Code | Same brand (including "on behalf of"), within 45 days. Deterministic and explainable |
| Below-rate, usage, gifting-value, deadline flags | Code | Arithmetic against the profile |
| Recommended action | Code | A table of flags to action, so it is predictable and testable |
| Draft replies | Templates filled with verified numbers | A reply the creator might send as-is should never contain a figure a language model made up |

### Treating email as untrusted

Several layers, because no single one is enough:

1. An email that contains instructions aimed at an AI (E-07) is flagged, categorised as a scam by code, and **never sent to the model at all**.
2. The prompt wraps the email in tags and says to treat it as data. That is a courtesy to the model, not the defence.
3. The model has no tools and cannot act. Its output only fills fields.
4. Model output is validated. A fee that does not appear in the email's text is dropped. A brand name that appears nowhere in the email is dropped. A content-rule violation must match a rule in the profile word for word.
5. If the model disagrees with a hard rule, the rule wins, and the disagreement is recorded on the email (`llm_category` vs `category`).
6. Draft replies are templates. The creator's phone, address and bank details are never inputs to anything.
7. Text from emails is stripped of Markdown before it goes into the report, so a brand name cannot render as a link or heading.

### Calls I made that are arguable

- **E-06 (Chai & Co, 25k, no deadline or usage)** is `deal_offer`, not `needs_more_info`. It has a deliverable and a price. It is flagged below rate, and the draft asks for the missing details while countering.
- **E-12 (SnapMeal, reel by 1 November, received 10 November)** is `deal_offer` with an `impossible_deadline` flag and the action "ask for details". The offer is real and above rate; the date is the problem. I would not argue with `needs_more_info`, so `expected.json` accepts either and reports strict and lenient scores separately.
- **E-02 is a deal offer** even though its own text has no deliverables ("same deliverables"). See the evaluation below; this was the one thing the first run got wrong.
- **Dew Lab's recommendation is negotiate, not accept.** The latest offer (₹1,00,000) is 9% under the rate card for 2 reels and 3 stories (₹1,10,000), and the brand had offered ₹1,20,000 first. The draft points at that.
- **Replies never name the exclusivity partner.** The Pixelon decline says "smartphones category until 31 Jan 2027", not "Nova Phones". A test guards this.
- **E-15 says an attachment exists, but the tool only sees message text.** It is flagged "open the original email", not treated as a brand that forgot to attach something.

## Evaluation

`data/expected.json` holds my answers for all 15 emails: category, key fields, deal groupings, required and forbidden flags, and recommended action. I wrote it before any of the system code. Run `python3 -m dealdesk eval` to reproduce.

### The provided inbox, rules only

| Check | Result |
|---|---|
| Category (strict) | 15/15 |
| Extracted fields | 45/45 |
| Deals grouped as expected | 9/9 |
| Recommended action | 13/13 |
| Flags present / absent as expected | 19/19 |

**This number is not as good as it looks.** I read these 15 emails before writing the rules, so they are tuned to this inbox. The first run scored 14/15: E-02 ("same deliverables", no details of its own) was classed `needs_more_info`. The fix is general (a follow-up that restates a price inherits its thread's context), but I only validated it on this inbox.

### A held-out set, rules only

To check how much of that is overfitting, I wrote 15 new emails (`data/holdout/`) and their expected answers before running them. They include edge cases designed to test the limits of deterministic rules.

| Check | Result |
|---|---|
| Category (strict) | **11/15** |
| Extracted fields | 21/23 |

What it got wrong, and why:

| Email | Expected | Got | Cause |
|---|---|---|---|
| H-07 Hindi in Devanagari, "बजट 30000 रुपये" | deal_offer | spam | Rules only know Latin script. No fee, no deliverables found |
| H-08 free sneakers, "no strings" | needs_more_info | spam | A gift with no ask contains none of my collaboration keywords |
| H-12 "join our creator club for Rs 499" | scam | spam | The pay-to-join pattern wants the word "fee" or "pay" |
| H-13 "you can bet on fast payment" | deal_offer | not_a_fit | The gambling keyword `bet` fires on an idiom. A real deal would be wrongly declined |
| H-15 agency, "our client Zest Drinks" | brand Zest Drinks | SparkReach | Agency detection only knows "on behalf of" |

Two earlier holdout gaps were cleanly addressed in the rules parser: H-10 ("limit usage rights to 6 months") now parses reverse usage phrasing, and H-14 ("Budget: 75,000/-") now recognises standard Indian `/-` currency notation.

Rules-only is a reasonable floor and a safety net. It is not a classifier I would trust on a different creator's inbox. The remaining failures are exactly what a model should fix: non-Latin scripts, unusual phrasing, and idioms.

H-13 remains a deliberate trade-off. A hard keyword rule that forces `not_a_fit` can reject a real paying deal. That trade is intentional (a creator would rather decline a fantasy-sports app by mistake than promote one), but in production it needs a human-readable reason on screen (which it has) and an easy manual override.

### The model path

The project includes an optional LLM integration designed for OpenAI-compatible endpoints (`gemini-3.5-flash`, `groq`, `openrouter`, or local `ollama`).

What is verified by automated tests (running against local HTTP mock servers):
- The client formats OpenAI-compatible requests, parses fenced/raw JSON, and caches responses to disk.
- Retries and backoff for HTTP 429 rate limits are implemented and covered by unit tests.
- Guardrails catch hostile outputs: a model falling for a scam is overruled by deterministic safety rules (E-03).
- Grounding checks catch hallucinations: fees or brand names invented by the model are dropped.
- Malformed outputs or network errors gracefully fall back to rule-based analysis, surfacing a visible CLI warning (`WARNING: X of Y emails used rules because the model failed.`).

**Live verification note**: During live integration testing in this environment with a Gemini API key, the live API endpoint could not be verified because the account hit free-tier quota limits (HTTP 429: "Generate content requests per day limit exceeded on Free Tier"). The pipeline handled this cleanly by falling back to the rules engine and logging the required warning. When a valid key and quota are available, running `python -m dealdesk eval --mode llm --no-cache` exercises the live API path directly.

## Cost, time and scale

Rules-only: well under a second for the whole inbox, free.

With a model, one call per email except quarantined ones. By character count the prompt is about 780 input tokens (a 2.4 KB fixed prompt plus about 650 characters per email) and the reply is maybe 250 tokens, so roughly 1,000 tokens per email. These are estimates, not measurements. On free tiers that costs nothing per email. At typical small-model paid prices it is a fraction of a cent. Latency I would expect at 1 to 3 seconds per call, which is roughly 15 to 45 seconds for this inbox, sequentially.

At 1,000 emails a day, that is about a million tokens and roughly 15 to 50 minutes of sequential calls. What changes:

- The code is sequential today. A worker pool of 8 to 16 gets it to minutes. Retry on 429 with backoff is already there.
- Free-tier daily caps will be the first limit. Check them against 1,000 requests a day before committing to one provider.
- Responses are cached on disk by hash, so re-runs and evals are free.
- A cheap pre-filter helps: newsletters, injections and exact duplicates never need a model.
- The 45-day grouping window and exact-brand matching get slow and sloppy with thousands of emails. It wants an index by sender domain and a real thread ID from the mail provider.

## What I'd build next with another week

1. Run the model path against both sets, publish the numbers, and tune the prompt on the misses. A real model-vs-rules disagreement report is the best test data I could get.
2. Replace the hard-coded content-rule detectors with the model judging the profile's rules, using the keyword hits only as a tripwire and showing the evidence for a human to confirm.
3. A review UI: one card per deal with accept, edit and discard on the draft, and a "this flag is wrong" button that feeds a growing eval set.
4. Read attachments (PDF briefs) in a sandboxed step, since E-15 shows that is where real terms live.
5. Real mail input (Gmail API) with thread IDs, and sender reputation: first-seen domain, SPF/DKIM result, domain age.
6. Money and usage nuance: advance vs net-60 payment, exclusivity clauses inside offers, a usage-rights price calculator instead of "priced separately".
7. A per-creator rate card that learns from deals they accept.

## Where I used AI tools

I used AI coding assistants (Claude Code and Antigravity) across several iterative development sessions. The assistant helped scaffold the module structure, draft initial regexes, build unit tests, and implement edge-case handling.

The design constraints and architecture were driven by the task requirements:
- The model reads and code decides; deterministic rules always retain veto power.
- Zero external runtime dependencies (Python standard library only).
- Test-driven validation: `data/expected.json` was authored before the pipeline was finalized.
- The held-out set was written to deliberately probe weaknesses in heuristic parsing.

Key issues identified and corrected across development sessions:
- E-02 misclassification: follow-up emails without repeated deliverables now inherit thread context.
- Brand matching: added support for possessive brand names like "SnapMeal's".
- False positives in prompt-injection and fee detectors: narrowed injection patterns to require explicit qualifiers (e.g. "previous/system instructions", "system prompt", "follow new instructions instead") and AI targets rather than isolated words, preventing false alerts on business phrases (such as "assistant brand manager", "mark as urgent", "follow the new instructions in the attached brief", or "do not ignore the rules of our giveaway"), and refined pay-to-join patterns so normal brand fee commitments ("we will pay your fee") are not flagged.
- Model failure visibility: added explicit CLI warnings when model calls fail and fall back to rules.

## Layout

```
dealdesk/
  parsing.py    amounts and dates
  signals.py    injection, scam, content-rule and exclusivity checks
  extract.py    rule-based extraction
  llm.py        optional model client, prompt, output validation
  pipeline.py   per-email analysis, category decision, deal grouping
  risk.py       rate card, usage, deadline and gifting checks
  drafts.py     reply templates
  report.py     summary.md and drafts.md
  evaluate.py   scoring against expected.json
  cli.py
data/           inbox, creator profile, expected answers, held-out set
tests/
sample_output/  committed rules-only run and both eval reports
```

## Known limits

- Prompt-injection heuristics: pattern matching checks for explicit hostile qualifiers (`previous/prior instructions`, `system prompt`, override directives, and AI target roles). While patterns have been narrowed to permit standard brief language ("follow the new instructions in the attached brief", "do not ignore the rules of our giveaway"), regex heuristics cannot replace semantic parsing for arbitrary unseen phrasing.
- Content rules and exclusivity categories are matched by keyword. Unknown categories fall back to a literal match on the category name.
- Payment terms are never parsed, so every deal gets an info flag saying they are not stated.
- Currency is INR or USD only.
- Grouping is by brand name and date, not by real email thread.
- Replies are in English, except a Hinglish template for rate negotiations when the sender writes in Hinglish.
- It has been run on one creator's 15 emails and one set of 15 more. That is not a lot.
