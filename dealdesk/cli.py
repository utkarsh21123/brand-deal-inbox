import argparse
import json
import sys
import time
from pathlib import Path

from . import evaluate, llm, pipeline, report


def _load(data_dir):
    d = Path(data_dir)
    return (json.loads((d / "inbox.json").read_text(encoding="utf-8")),
            json.loads((d / "creator_profile.json").read_text(encoding="utf-8")), d)


def _client(mode, cache):
    if mode == "rules":
        return None
    llm.load_env()
    client = llm.Client.from_env(cache_dir=cache)
    if client is None and mode == "llm":
        sys.exit("--mode llm needs LLM_PROVIDER (and LLM_API_KEY) set. See .env.example.")
    return client


def _run(args):
    inbox, profile, data = _load(args.data)
    client = _client(args.mode, None if args.no_cache else ".cache")
    start = time.time()
    results, deals = pipeline.run(inbox, profile, client)
    return results, deals, profile, data, client, time.time() - start


def _warn_fallback(results):
    failed = sum(1 for r in results if r.source == "rules (llm failed)")
    if failed:
        print(f"WARNING: {failed} of {len(results)} emails used rules because the model failed.", file=sys.stderr)


def cmd_run(args):
    results, deals, profile, _, client, secs = _run(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "emails.json").write_text(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "deals.json").write_text(json.dumps([d.to_dict() for d in deals], indent=2, ensure_ascii=False), encoding="utf-8")
    text = report.summary(results, deals, profile)
    (out / "summary.md").write_text(text, encoding="utf-8")
    (out / "drafts.md").write_text(report.drafts_file(deals), encoding="utf-8")
    print(text)
    _warn_fallback(results)
    how = f"{client.provider}/{client.model}, {client.calls} calls, {client.cache_hits} cached" if client else "rules only"
    print(f"[{len(results)} emails, {len(deals)} deals, {secs:.1f}s, {how}] wrote {out}/", file=sys.stderr)


def cmd_eval(args):
    results, deals, _, data, client, _ = _run(args)
    expected = json.loads((data / "expected.json").read_text(encoding="utf-8"))
    mode = f"{client.provider}/{client.model} + rules" if client else "rules only"
    text = evaluate.render(evaluate.score(expected, results, deals), mode)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "eval.md").write_text(text, encoding="utf-8")
    print(text)
    _warn_fallback(results)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="dealdesk", description="Triage a creator's brand-deal inbox.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("run", cmd_run, "process the inbox and write reports"),
                            ("eval", cmd_eval, "score a run against data/expected.json")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--data", default="data", help="folder with inbox.json and creator_profile.json")
        s.add_argument("--out", default="out")
        s.add_argument("--mode", choices=["auto", "rules", "llm"], default="auto",
                       help="auto: use a model if one is configured; rules: never call a model; llm: require one")
        s.add_argument("--no-cache", action="store_true", help="ignore the on-disk model response cache")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
