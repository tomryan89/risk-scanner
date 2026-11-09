"""Phase 3: locate the principal risks section (the report's risk chapter) and save it as text.

Reports name and lay out this chapter differently ("Principal risks and uncertainties", "Risk management", "Key
risks", ...), usually with a running header repeated on each page ("... continued"). So we:
  1. find standalone heading lines that name a risk chapter (not sentences, not contents-page lines with page numbers);
  2. chain hits that are close together into clusters (a chapter's pages);
  3. choose the cluster that talks most about "principal risk(s)";
  4. extend it to the next major section heading (viability statement, Section 172, governance, ...).
If no cluster mentions principal risks enough, the result is "not found": we never guess.
The chapter often includes the emerging risks discussion; we flag whether it does.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from scanner import config, db, textify

_CONT = r"(?:\s*[:\-–—]?\s*\(?continued\)?)?"
HEADING = re.compile(
    r"^(?:our |group |the group.s |how we manage (?:our )?)?"
    r"(?:"
    r"(?:principal(?: (?:and|&) emerging)?|key|significant|main) risks?(?: (?:and|&) uncertainties)?"
    r"(?: \(risk factors\))?"
    r"|risk management(?: (?:and|&) principal risks?(?: factors)?)?"
    r"|managing (?:our )?risks?|our approach to risk(?: management)?|risk review|risk report"
    r"|(?:assessment|management|summary) of (?:our )?principal risks(?: (?:and|&) uncertainties)?"
    r"|risks? (?:and|&) uncertainties|risk factors(?: (?:and|&) uncertainties)?|risk overview"
    r"|top (?:and emerging )?risks"
    r")"
    r"(?:\s*[–—-]\s*(?:financial|non-financial|strategic|operational|business|group))?"  # "Principal risks – financial"
    + _CONT + r"\.?$",
    re.I,
)
# Headings that start a different part of the report. Deliberately excludes words that reports repeat as page
# navigation tabs on every page ("Governance", "Sustainability", "Strategic report", "Financial statements").
STOP = re.compile(
    r"^(?:(?:our |the |group.s |group )?(?:longer[- ]term |long[- ]term )?viability statement"
    r"|(?:statement of )?going concern(?: and viability)?(?: statement)?$"
    r"|(?:directors.? duties under )?section 172(?:\(1\))?(?: statement)?|s172 statement"
    r"|non-financial and sustainability information(?: statement)?"
    r"|corporate governance report|chair.?s (?:introduction|letter)"
    r"|directors.? report$|independent auditor)",
    re.I,
)
EMERGING = re.compile(r"^(?:spotlight: )?emerging (?:and [a-z]+ )?risks?\b", re.I)
PR_MENTION = re.compile(r"principal\s+risk", re.I)
PR_HEADING = re.compile(
    r"(?:principal|key|significant|main|top) risks?|risks? (?:and|&) uncertainties|risk factors", re.I)

MAX_GAP = 800  # lines between headings of the same chapter
MIN_TAIL = 450  # always keep at least this many lines after the last heading (unless a stop heading comes first)
MAX_QUIET = 250  # beyond that, stop once this many lines in a row don't mention risk
RISK_WORD = re.compile(r"\brisk", re.I)
MAX_LINES = 4000  # sanity cap for one chapter
MIN_PR_MENTIONS = 3
RISK_STRUCT = re.compile(
    r"^(?:description of (?:the )?risk|how we (?:mitigate|manage) (?:this|the) risk|risk owners?|mitigations?|"
    r"mitigating actions|key mitigations?|risk trend|change in (?:the )?year|link to strategy|potential impact)\b",
    re.I)
MIN_STRUCT = 8


@dataclass
class Section:
    found: bool
    reason: str = ""
    start: int = 0
    end: int = 0
    lines: list[str] = field(default_factory=list)
    has_emerging: bool = False
    pr_mentions: int = 0
    headings: list[str] = field(default_factory=list)


def _is_heading(line: str) -> bool:
    return len(line) <= 90 and line[:1].isupper() and not re.search(r"\d\s*$", line) and bool(HEADING.match(line))


def _is_stop(line: str) -> bool:
    return len(line) <= 80 and line[:1].isupper() and not re.search(r"\d\s*$", line) and bool(STOP.match(line))


POINTER = re.compile(r"set out (?:in|on)|(?:are|is) described (?:in|on)|can be found (?:in|on)|see pages? \d", re.I)


def _heading_at(lines: list[str], i: int) -> str | None:
    """The heading starting at line i, also when it wraps onto a second line ("PRINCIPAL AND EMERGING RISKS AND" /
    "UNCERTAINTIES")."""
    line = lines[i]
    if _is_heading(line):
        return line
    if i + 1 < len(lines) and len(line) <= 50 and len(lines[i + 1]) <= 40:
        joined = f"{line} {lines[i + 1]}"
        if _is_heading(joined):
            return joined
    return None


def find_section(lines: list[str]) -> Section:
    heads = {i: h for i in range(len(lines)) if (h := _heading_at(lines, i))}
    # skip the second line of a wrapped heading we already matched on the line before
    hits = [i for i in heads if not (i - 1 in heads and heads[i - 1].endswith(lines[i]) and heads[i - 1] != lines[i - 1])]
    if not hits:
        return Section(False, "no risk chapter heading found")

    stops = [i for i, l in enumerate(lines) if _is_stop(l)]
    clusters: list[list[int]] = [[hits[0]]]
    for i in hits[1:]:
        prev = clusters[-1][-1]
        if i - prev <= MAX_GAP and not any(prev < s < i for s in stops):
            clusters[-1].append(i)
        else:
            clusters.append([i])

    def span(c: list[int]) -> tuple[int, int]:
        """From the first heading to a stop heading; otherwise at least MIN_TAIL lines past the last heading, and
        further while the text keeps talking about risk. Erring long is deliberate: extra text costs a little
        Haiku time, a cut-off section loses risks."""
        start, last = c[0], c[-1]
        limit = min(len(lines), start + MAX_LINES)
        end, quiet = limit, 0
        for j in range(last + 1, limit):
            if _is_stop(lines[j]):
                end = j
                break
            quiet = 0 if RISK_WORD.search(lines[j]) else quiet + 1
            if quiet >= MAX_QUIET and j >= last + MIN_TAIL:
                end = max(j - quiet + 1, last + MIN_TAIL)
                break
        return start, end

    def score(c: list[int]) -> int:
        s, e = span(c)
        return sum(1 for l in lines[s:e] if PR_MENTION.search(l))

    def pointer(c: list[int]) -> bool:  # a lone heading over "…are set out in the Principal Risks section…"
        return len(c) == 1 and any(POINTER.search(l) for l in lines[c[0] + 1: c[0] + 8])

    def named(c: list[int]) -> bool:  # has a heading that actually says "principal/key risks"
        return not pointer(c) and any(PR_HEADING.search(heads[i]) for i in c)

    if not any(PR_MENTION.search(l) for l in lines) and not any(named(c) for c in clusters):
        return Section(False, "report never mentions principal risks (financial statements only, or not in English?)")
    def structure(c: list[int]) -> int:  # lines that only appear in risk-by-risk write-ups
        s_, e_ = span(c)
        return sum(1 for l in lines[s_:e_] if len(l) <= 60 and RISK_STRUCT.match(l))

    # Prefer a chapter with a "principal risks" heading, or one laid out risk by risk ("Description of risk",
    # "Risk owner", "How we mitigate"): Airtel Africa's real chapter is headed "Managing our risk", while a committee
    # report elsewhere has a "Principal risks" sub-heading that only points to it.
    best = max(clusters, key=lambda c: (named(c) or structure(c) >= MIN_STRUCT, score(c) + structure(c), len(c)))
    pr = score(best)
    # A chapter headed "Principal risks…" counts even if small companies rarely repeat the phrase.
    if pr < MIN_PR_MENTIONS and not named(best):
        return Section(False, f"risk headings found, but none near enough mentions of principal risks ({pr})")
    s, e = span(best)
    body = lines[s:e]
    return Section(
        True, start=s, end=e, lines=body, pr_mentions=pr,
        has_emerging=any(EMERGING.match(l) for l in body) or any(re.search(r"emerging\s+risk", l, re.I) for l in body),
        headings=sorted({heads[i] for i in best}),
    )


# ---------- orchestration ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    ticker       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,   -- found | not_found | error
    reason       TEXT,
    path         TEXT,
    words        INTEGER,
    start_pct    REAL,            -- where in the report the chapter starts (0-100)
    pr_mentions  INTEGER,
    has_emerging INTEGER,
    headings     TEXT,
    updated      TEXT NOT NULL
);
"""


def run(tickers: list[str] | None = None, redo: bool = False, log=print) -> None:
    con = db.connect()
    con.executescript(SCHEMA)
    out_dir = config.DATA_DIR / "sections"
    out_dir.mkdir(parents=True, exist_ok=True)
    q = "SELECT ticker, path FROM reports WHERE status = 'downloaded'"
    rows = [r for r in con.execute(q) if not tickers or r["ticker"] in tickers]
    for n, r in enumerate(rows, 1):
        t = r["ticker"]
        if not redo and con.execute("SELECT 1 FROM sections WHERE ticker = ?", (t,)).fetchone():
            log(f"[{n}/{len(rows)}] {t}: already done, skipped")
            continue
        try:
            lines = textify.report_to_lines(Path(r["path"]))
            sec = find_section(lines)
        except Exception as e:
            con.execute("INSERT OR REPLACE INTO sections (ticker, status, reason, updated) VALUES (?,?,?,?)",
                        (t, "error", f"{type(e).__name__}: {e}", db.now()))
            con.commit()
            log(f"[{n}/{len(rows)}] {t}: error ({e})")
            continue
        path = None
        if sec.found:
            path = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', t).strip('_')}.txt"
            path.write_text("\n".join(sec.lines) + "\n", encoding="utf-8")
        words = sum(len(l.split()) for l in sec.lines)
        con.execute(
            "INSERT OR REPLACE INTO sections VALUES (?,?,?,?,?,?,?,?,?,?)",
            (t, "found" if sec.found else "not_found", sec.reason or None, str(path) if path else None, words,
             round(100 * sec.start / max(len(lines), 1), 1), sec.pr_mentions, int(sec.has_emerging),
             " | ".join(sec.headings), db.now()),
        )
        con.commit()
        if sec.found:
            log(f"[{n}/{len(rows)}] {t}: found, {words:,} words from {100 * sec.start / len(lines):.0f}% of the report"
                f"{', incl. emerging risks' if sec.has_emerging else ''}")
        else:
            log(f"[{n}/{len(rows)}] {t}: NOT FOUND ({sec.reason})")


# ---------- whole-report mode (when the section finder fails) ----------

FIN_START = re.compile(r"^independent auditors?['’]? report\b|^independent auditors?['’]? report to the members", re.I)


def front_text(ticker: str) -> Path | None:
    """Everything before the financial statements (the first 'Independent auditor's report' heading after the
    first 20% of the report), saved to data/report_front/<ticker>.txt, for a model to find the risks itself."""
    con = db.connect()
    r = con.execute("SELECT path FROM reports WHERE ticker=? AND status='downloaded'", (ticker,)).fetchone()
    if not r:
        return None
    lines = textify.report_to_lines(Path(r["path"]))
    start = len(lines) // 5
    cut = next((i for i in range(start, len(lines)) if len(lines[i]) <= 80 and FIN_START.match(lines[i])), len(lines))
    out_dir = config.DATA_DIR / "report_front"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', ticker).strip('_')}.txt"
    path.write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8")
    return path
