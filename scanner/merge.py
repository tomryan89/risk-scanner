"""Phase 7: combine the classification runs into one final verdict per company (run `final-<suffix>`).

Order of preference for each company:
  1. Opus on the whole report (`report` run): used where the section finder failed or picked doubtful text.
  2. Opus tie-break at high effort (`tiebreak` run): where Haiku and Opus disagreed on the section.
  3. Opus and Haiku agree on the section: Opus's row (its themes were better on the test set).
  4. Only one of them answered: that row.
A `confirm` run (Opus on the whole report, for "no" verdicts a cheap whole-report Haiku sweep flagged) overrides all.
Every final row records its `basis` (how it was decided) and what the other model said, so disagreements are visible.
"""

from scanner import classify, db

COLS = [r for r in ("ticker", "run", "model", "effort", "status", "verdict", "themes", "quote", "risk_title",
                    "quote_ok", "supply_chain", "tprm", "emerging", "reason", "raw", "in_tokens", "out_tokens",
                    "cache_read", "cache_write", "batch_id", "updated", "main_theme")]


def ensure_columns(con) -> None:
    classify.ensure_table(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(classifications)")}
    for c in ("basis", "other_view"):
        if c not in cols:
            con.execute(f"ALTER TABLE classifications ADD COLUMN {c} TEXT")


def build(final: str, haiku: str, opus: str, report: str, tiebreak: str | None = None,
          confirm: str | None = None, log=print) -> None:
    con = db.connect()
    ensure_columns(con)

    def done(run):
        return {r["ticker"]: r for r in con.execute(
            "SELECT * FROM classifications WHERE run=? AND status='done'", (run,))} if run else {}

    h, o, rep, tb, cf = done(haiku), done(opus), done(report), done(tiebreak), done(confirm)
    con.execute("DELETE FROM classifications WHERE run=?", (final,))
    counts = {}
    for t in sorted(set(h) | set(o) | set(rep) | set(cf)):
        other = None
        if t in cf:  # a whole-report sweep said the first "no" missed something; Opus re-read the whole report
            row, basis = cf[t], "Re-checked: Opus read the whole report after a sweep flagged a possible miss"
            prev = rep.get(t) or tb.get(t) or o.get(t) or h.get(t)
            other = f"Earlier verdict: {prev['verdict']}" if prev else None
        elif t in rep:
            row, basis = rep[t], "Opus read the whole report (section finder failed or doubtful)"
            if t in h:
                other = f"Haiku on the extracted section: {h[t]['verdict']}"
        elif t in h and t in o:
            if h[t]["verdict"] == o[t]["verdict"]:
                row, basis = o[t], "Haiku and Opus agree"
            elif t in tb:
                row, basis = tb[t], "Haiku and Opus disagreed; Opus re-read (high effort, or whole report) and decided"
                other = f"Haiku: {h[t]['verdict']}; Opus (medium): {o[t]['verdict']}"
            else:
                row, basis = o[t], "Haiku and Opus disagree: check"
                other = f"Haiku: {h[t]['verdict']}"
        else:
            row = o.get(t) or h[t]
            basis = "Opus only" if t in o else "Haiku only"
        vals = [row[c] for c in COLS]
        vals[COLS.index("run")] = final
        con.execute(f"INSERT INTO classifications ({', '.join(COLS)}, basis, other_view) "
                    f"VALUES ({', '.join('?' * (len(COLS) + 2))})", vals + [basis, other])
        counts[basis] = counts.get(basis, 0) + 1
    con.commit()
    for b, n in sorted(counts.items(), key=lambda x: -x[1]):
        log(f"{n:4}  {b}")


def disagreements(haiku: str, opus: str, report: str) -> list[str]:
    con = db.connect()
    q = ("SELECT h.ticker FROM classifications h JOIN classifications o ON o.ticker=h.ticker AND o.run=? "
         "WHERE h.run=? AND h.status='done' AND o.status='done' AND h.verdict != o.verdict "
         "AND h.ticker NOT IN (SELECT ticker FROM classifications WHERE run=? AND status='done')")
    return [r["ticker"] for r in con.execute(q, (opus, haiku, report))]
