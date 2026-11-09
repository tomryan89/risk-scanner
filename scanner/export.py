"""Phase 6: one row per company (all of data/companies.csv) from a classify run -> output/results_<run>.xlsx.

Companies without a result are kept as "couldn't check", with the reason from whichever step stopped them.
"""

import csv
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from scanner import classify, config, db
from scanner.testset import _viewer_urls

COLS = ["ticker", "company", "industry", "supersector", "verdict", "verdict check", "how decided", "other model said", "main theme", "themes", "risk title", "quote",
        "quote verified", "supply chain risk", "TPRM programme", "emerging risks", "model's reason",
        "couldn't check because", "section words", "FY end", "report source", "full report (online viewer)"]
SHORT_SECTION = 1500  # words; a 'no' from a shorter section may come from the wrong part of the report
ORDER = {"yes": 0, "passing mention": 1, "no": 2, "couldn't check": 3}
FILL = {"yes": "C6EFCE", "passing mention": "FFF2CC", "no": "FFFFFF", "couldn't check": "E7E6E6"}


def rows(run: str) -> list[dict]:
    con = db.connect()
    classify.ensure_table(con)
    rep = {r["ticker"]: r for r in con.execute("SELECT * FROM reports")}
    sec = {r["ticker"]: r for r in con.execute("SELECT * FROM sections")}
    cls = {r["ticker"]: r for r in con.execute("SELECT * FROM classifications WHERE run=?", (run,))}
    viewers = _viewer_urls()
    out = []
    with (config.DATA_DIR / "companies.csv").open(encoding="utf-8") as f:
        for c in csv.DictReader(f):
            t = c["ticker"]
            r, s, k = rep.get(t), sec.get(t), cls.get(t)
            row = {"ticker": t, "company": c["name"].title(), "industry": c["icb_industry"],
                   "supersector": c["icb_supersector"], "FY end": r["period_end"] if r else None,
                   "report source": r["source"] if r and r["status"] == "downloaded" else None,
                   "full report (online viewer)": (viewers.get(r["filing_id"], "") if r["filing_id"] else "")
                   or (r["package_url"] if r["source"] != "filings.xbrl.org" else "") if r else ""}
            if s and s["status"] == "found":
                row["section words"] = s["words"]
            why = None
            if not r:
                why = "report not downloaded yet"
            elif r["status"] != "downloaded":
                why = r["reason"]
            elif not k and not s:
                why = "risk section not extracted yet"
            elif not k and s["status"] != "found":
                why = f"risk section not found ({s['reason'] or s['status']})"
            elif not k:
                why = "not classified yet"
            elif k["status"] != "done":
                why = f"classifier {k['status']}: {k['reason'] or ''}".strip()
            elif k["verdict"] == "couldn't check":
                why = f"model: {k['reason']}"
            if why:
                row.update(verdict="couldn't check", **{"couldn't check because": why})
            else:
                row.update({"verdict": k["verdict"], "main theme": k["main_theme"], "themes": k["themes"] or None,
                            "risk title": k["risk_title"] or None, "quote": k["quote"] or None,
                            "quote verified": None if not k["quote"] else ("yes" if k["quote_ok"] else "NO: check"),
                            "supply chain risk": "yes" if k["supply_chain"] else "no",
                            "TPRM programme": "yes" if k["tprm"] else "no", "emerging risks": k["emerging"],
                            "model's reason": k["reason"],
                            "how decided": k["basis"] if "basis" in k.keys() else None,
                            "other model said": k["other_view"] if "other_view" in k.keys() else None})
                if r["reason"] and r["reason"].startswith("older report"):
                    row["verdict check"] = f"{r['reason']} (a newer one wasn't available)"
                basis = (k["basis"] if "basis" in k.keys() else None) or ""
                if (k["verdict"] == "no" and s and s["status"] == "found" and s["words"] < SHORT_SECTION
                        and not basis.startswith("Opus read")):
                    row["verdict check"] = f"check: section only {s['words']} words, may be the wrong part"
            out.append(row)
    out.sort(key=lambda x: (ORDER[x["verdict"]], x["company"]))
    return out


def write(run: str, path: Path) -> Counter:
    data = rows(run)
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(COLS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for d in data:
        ws.append([d.get(c) for c in COLS])
        r = ws.max_row
        fill = PatternFill("solid", fgColor=FILL[d["verdict"]])
        for c in ws[r]:
            c.fill = fill
            c.alignment = Alignment(vertical="top", wrap_text=c.column_letter in ("F", "G", "H", "L", "Q", "R"))
        link = d["full report (online viewer)"]
        if link:
            cell = ws.cell(r, COLS.index("full report (online viewer)") + 1)
            cell.value, cell.hyperlink, cell.font = "open report", link, Font(color="0563C1", underline="single")
    widths = dict(zip("ABCDEFGHIJKLMNOPQRSTUV", [8, 30, 18, 18, 15, 25, 30, 24, 25, 24, 30, 70, 10, 10, 10, 16, 60, 40, 9, 11, 16, 14]))
    for k, v in widths.items():
        ws.column_dimensions[k].width = v
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    s = wb.create_sheet("Summary")
    counts = Counter(d["verdict"] for d in data)
    s.append([f"Run {run}: {len(data)} companies"])
    s["A1"].font = Font(bold=True)
    s.append([])
    s.append(["Verdict", "Companies"])
    for v in ORDER:
        s.append([v, counts[v]])
    s.append([])
    s.append(["Industry"] + list(ORDER))
    for ind in sorted({d["industry"] for d in data}):
        s.append([ind] + [sum(1 for d in data if d["industry"] == ind and d["verdict"] == v) for v in ORDER])
    s.append([])
    s.append(["Main theme (yes + passing mention)", "yes", "passing mention"])
    for th in classify.THEMES:
        s.append([th] + [sum(1 for d in data if d.get("main theme") == th and d["verdict"] == v)
                         for v in ("yes", "passing mention")])
    s.append([])
    s.append(["Couldn't check because", "Companies"])
    whys = Counter(_why_group(d["couldn't check because"]) for d in data if d["verdict"] == "couldn't check")
    for w, n in whys.most_common():
        s.append([w, n])
    s.column_dimensions["A"].width = 45
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return counts


def _why_group(why: str) -> str:
    if why.startswith("stale"):
        return "stale: latest report on XBRL is over 18 months old"
    if why.startswith("risk section not found"):
        return "risk section not found in the report"
    if why.startswith("model:"):
        return "model: no principal risks section in what it read"
    if why.startswith("error:"):
        return "download error"
    return why
