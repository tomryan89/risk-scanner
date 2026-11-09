"""Command-line entry point: python -m scanner <command>."""

import argparse
import sys
from pathlib import Path

from scanner import config


def cmd_check(_args: argparse.Namespace) -> int:
    """Show the configuration and confirm the folders and API key are in place (never prints the key)."""
    ok = True
    print(f"Python       {sys.version.split()[0]}")
    for name, path in [("data", config.DATA_DIR), ("output", config.OUTPUT_DIR), ("reports", config.REPORTS_DIR)]:
        exists = path.is_dir()
        ok &= exists
        print(f"{name:<12} {path}  [{'ok' if exists else 'MISSING'}]")
    key = config.api_key()
    key_ok = bool(key and key.startswith("sk-ant-"))
    ok &= key_ok
    print(f"API key      {'loaded from .env' if key_ok else 'MISSING or malformed (expected ANTHROPIC_API_KEY=sk-ant-...)'}")
    return 0 if ok else 1


def cmd_companies(args: argparse.Namespace) -> int:
    """Phase 1: write data/companies.csv (+ companies_excluded.csv) from the LSE Instrument list."""
    from collections import Counter

    from scanner import companies

    src = args.instruments or companies.latest_instrument_list(config.DATA_DIR / "raw")
    if not src or not src.is_file():
        print("No Instrument list found. Download it from londonstockexchange.com/reports?tab=issuers "
              "into data/raw/ as Instrument_list_YYYY-MM-DD.xlsx, or pass --instruments PATH.")
        return 1
    kept, excluded, stats = companies.build(src)
    out = config.DATA_DIR / "companies.csv"
    companies.write_csv(out, companies.COMPANY_FIELDS, kept)
    companies.write_csv(config.DATA_DIR / "companies_excluded.csv", companies.EXCLUDED_FIELDS, excluded)

    print(f"Source: {src.name}")
    print(f"Main Market companies with shares: {stats['main_market_companies']}")
    print(f"  kept (operating companies):      {stats['kept']}  -> {out}")
    print(f"  excluded:                        {stats['excluded']}  -> companies_excluded.csv")
    for reason, n in Counter(e["reason"] for e in excluded).most_common():
        print(f"    {n:>4}  {reason}")
    print("Kept, by listing category:")
    for cat, n in Counter(c["listing_category"] for c in kept).most_common():
        print(f"    {n:>4}  {cat}")
    return 0


def cmd_reports(args: argparse.Namespace) -> int:
    """Phase 2: download each company's latest annual report package."""
    import csv

    from scanner import reports

    path = config.DATA_DIR / "companies.csv"
    if not path.is_file():
        print("No data/companies.csv yet: run `python -m scanner companies` first.")
        return 1
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",")]
        by_ticker = {r["ticker"].upper(): r for r in rows}
        missing = [t for t in wanted if t not in by_ticker]
        if missing:
            print(f"Not in companies.csv: {', '.join(missing)}")
            return 1
        rows = [by_ticker[t] for t in wanted]
    elif args.limit:
        rows = rows[: args.limit]
    reports.run(rows, retry_failed=args.retry_failed, allow_older=args.allow_older)

    from scanner import db

    con = db.connect()
    tickers = [r["ticker"] for r in rows]
    q = f"SELECT status, COUNT(*) n FROM reports WHERE ticker IN ({','.join('?' * len(tickers))}) GROUP BY status"
    print("Summary:", ", ".join(f"{r['n']} {r['status']}" for r in con.execute(q, tickers)))
    return 0


def cmd_companies_house(args: argparse.Namespace) -> int:
    """Phase 2b: fill gaps from Companies House (UK-incorporated companies whose XBRL route failed)."""
    from scanner import companies_house

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    companies_house.run(tickers)
    return 0


def cmd_websites(args: argparse.Namespace) -> int:
    """Phase 2c: download reports listed in data/website_reports.csv for companies still missing one."""
    from scanner import websites

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    websites.run(tickers, redo=args.redo, allow_older=args.allow_older)
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    """Phase 3: extract the principal risks chapter from each downloaded report."""
    from scanner import sections

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    sections.run(tickers, redo=args.redo)
    return 0


def cmd_testset(args: argparse.Namespace) -> int:
    """Phase 4: build output/test_set.xlsx for hand-labelling (keeps labels already entered)."""
    from scanner import db, testset

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = [r["ticker"] for r in db.connect().execute("SELECT ticker FROM reports ORDER BY ticker")]
    out = config.OUTPUT_DIR / "test_set.xlsx"
    n = testset.build(tickers, out)
    print(f"{n} companies -> {out}")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    """Phase 5: classify sections with Haiku (direct requests; for the test set)."""
    from scanner import classify, db

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = list(classify.gold_labels(config.OUTPUT_DIR / "test_set.xlsx"))
    classify.run_direct(tickers, args.run, args.effort, classify.MODELS[args.model])
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Phase 5: score a run against Tom's labels in output/test_set.xlsx."""
    from scanner import classify

    out = config.OUTPUT_DIR / f"phase5_{args.run}.md"
    print(classify.evaluate(args.run, config.OUTPUT_DIR / "test_set.xlsx", out))
    print(f"-> {out}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Phase 6: classify every company with a section via the Batch API (submit / status / wait)."""
    from scanner import batch, classify, db

    if args.action == "submit":
        tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
        batch.submit(args.run, args.effort, tickers, classify.MODELS[args.model], args.mode)
    elif args.action == "status":
        batch.collect(args.run)
    else:
        batch.wait(args.run, args.every)
    con = db.connect()
    rows = con.execute("SELECT * FROM classifications WHERE run=?", (args.run,)).fetchall()
    done = [r for r in rows if r["status"] == "done"]
    print(f"Run {args.run}: {len(done)} classified, {len(rows) - len(done)} errors/refusals, "
          f"cost so far ${sum(classify._cost(r) for r in rows):.2f}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Phase 6: one row per company -> output/results_<run>.xlsx."""
    from scanner import export

    out = config.OUTPUT_DIR / f"results_{args.run}.xlsx"
    counts = export.write(args.run, out)
    print(", ".join(f"{n} {v}" for v, n in counts.items()), f"-> {out}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Phase 7: combine Haiku, Opus, whole-report and tie-break runs into one final run."""
    from scanner import merge

    merge.build(args.final, args.haiku, args.opus, args.report, args.tiebreak, args.confirm)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scanner",
        description="Scan UK Main Market annual reports for third-party principal risks (not supply chain).",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("check", help="check folders and API key are set up")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("companies", help="phase 1: build data/companies.csv from the LSE Instrument list")
    p.add_argument("--instruments", type=Path, help="Instrument list .xlsx (default: newest in data/raw/)")
    p.set_defaults(func=cmd_companies)
    p = sub.add_parser("reports", help="phase 2: download latest annual reports (resumable)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--tickers", help="comma-separated tickers, e.g. TSCO,BP.")
    g.add_argument("--limit", type=int, help="only the first N companies")
    p.add_argument("--retry-failed", action="store_true", help="try earlier failures again")
    p.add_argument("--allow-older", action="store_true", help="download a stale report anyway, flagged as older")
    p.set_defaults(func=cmd_reports)
    p = sub.add_parser("companies-house", help="phase 2b: fill report gaps from Companies House (resumable)")
    p.add_argument("--tickers", help="comma-separated tickers (default: every failed XBRL company not tried yet)")
    p.set_defaults(func=cmd_companies_house)
    p = sub.add_parser("websites", help="phase 2c: download reports from company websites (data/website_reports.csv)")
    p.add_argument("--tickers", help="comma-separated tickers (default: every row in the links file)")
    p.add_argument("--redo", action="store_true", help="download again even if a website report was saved before")
    p.add_argument("--allow-older", action="store_true", help="download a stale report anyway, flagged as older")
    p.set_defaults(func=cmd_websites)
    p = sub.add_parser("sections", help="phase 3: extract the principal risks section from each report")
    p.add_argument("--tickers", help="comma-separated tickers (default: all downloaded)")
    p.add_argument("--redo", action="store_true", help="re-extract even if done before")
    p.set_defaults(func=cmd_sections)
    p = sub.add_parser("testset", help="phase 4: build the labelling sheet output/test_set.xlsx")
    p.add_argument("--tickers", help="comma-separated tickers (default: every company with a report record)")
    p.set_defaults(func=cmd_testset)
    p = sub.add_parser("classify", help="phase 5: classify sections with Haiku (default: the labelled test set)")
    p.add_argument("--run", required=True, help="name for this run, e.g. test-v3-medium")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--model", default="haiku", choices=["haiku", "sonnet", "opus"])
    p.add_argument("--tickers", help="comma-separated tickers")
    p.set_defaults(func=cmd_classify)
    p = sub.add_parser("evaluate", help="phase 5: score a classify run against Tom's labels")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_evaluate)
    p = sub.add_parser("batch", help="phase 6: classify all companies via the Batch API")
    p.add_argument("action", choices=["submit", "status", "wait"],
                   help="submit a batch / check it once and store results / check every --every seconds until done")
    p.add_argument("--run", required=True, help="e.g. full-2026-11")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--model", default="haiku", choices=["haiku", "sonnet", "opus"])
    p.add_argument("--tickers", help="comma-separated tickers (default: every company with a found section)")
    p.add_argument("--mode", default="section", choices=["section", "report"],
                   help="section = the extracted risk chapter; report = the front half of the whole report")
    p.add_argument("--every", type=int, default=300, help="seconds between checks for wait")
    p.set_defaults(func=cmd_batch)
    p = sub.add_parser("merge", help="phase 7: combine classify runs into one final verdict per company")
    p.add_argument("--final", default="final-2026-11")
    p.add_argument("--haiku", default="full-2026-11")
    p.add_argument("--opus", default="opus-sections-2026-11")
    p.add_argument("--report", default="report-opus-2026-11")
    p.add_argument("--tiebreak", default="tiebreak-2026-11")
    p.add_argument("--confirm", default="confirm-opus-report")
    p.set_defaults(func=cmd_merge)
    p = sub.add_parser("export", help="phase 6: write output/results_<run>.xlsx, one row per company")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
