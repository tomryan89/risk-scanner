"""Phase 4: build the labelling sheet for Tom's hand-labelled test set (output/test_set.xlsx).

One row per test company with links to the full report (filings.xbrl.org viewer) and the extracted section,
plus empty label columns with dropdowns matching docs/labelling-guide.md. Re-running keeps labels already entered.
"""

import csv
import json
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink

from scanner import config, db

XBRL = "https://filings.xbrl.org"
VERDICTS = ["yes", "passing mention", "no", "couldn't check"]
YES_NO = ["yes", "no"]
EMERGING = ["mentioned", "not mentioned", "no emerging risks section"]
THEMES = ["cyber & security", "sanctions, watchlists & PEPs", "bribery & corruption", "fraud & bad actors", "data protection",
          "outsourcing & resilience", "human rights & modern slavery"]

INFO_COLS = ["ticker", "name", "industry", "listing", "FY end", "section words", "section starts with",
             "full report (online viewer)", "section (tab)"]
LABEL_COLS = ["verdict", "themes", "quote", "supply chain", "TPRM programme", "emerging risks", "notes"]


def _viewer_urls() -> dict[str, str]:
    urls = {}
    for f in sorted((config.DATA_DIR / "xbrl_index").glob("filings-*.json")):
        for d in json.loads(f.read_text())["data"]:
            a = d["attributes"]
            if a.get("viewer_url"):
                urls[a["fxo_id"]] = XBRL + a["viewer_url"]
    return urls


def _tab(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", ticker)[:31] or "X"


def build(tickers: list[str], out: Path) -> int:
    con = db.connect()
    companies = {r["ticker"]: r for r in csv.DictReader((config.DATA_DIR / "companies.csv").open(encoding="utf-8"))}
    viewers = _viewer_urls()

    old = {}  # keep labels already typed in
    if out.exists():
        ws_old = openpyxl.load_workbook(out)["Test set"]
        hdr = [c.value for c in ws_old[1]]
        for row in ws_old.iter_rows(min_row=2, values_only=True):
            rec = dict(zip(hdr, row))
            if rec.get("ticker"):
                old[rec["ticker"]] = {k: rec.get(k) for k in LABEL_COLS}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test set"
    ws.append(INFO_COLS + LABEL_COLS)
    for t in tickers:
        c = companies.get(t, {})
        rep = con.execute("SELECT * FROM reports WHERE ticker = ?", (t,)).fetchone()
        sec = con.execute("SELECT * FROM sections WHERE ticker = ?", (t,)).fetchone()
        first = ""
        if sec and sec["path"]:
            first = " / ".join(Path(sec["path"]).read_text(encoding="utf-8").splitlines()[:3])[:120]
        info = [
            t, c.get("name", "").title(), c.get("icb_industry", ""),
            "transition" if "transition" in c.get("listing_category", "") else "ESCC",
            rep["period_end"] if rep else "",
            sec["words"] if sec and sec["status"] == "found" else "",
            first or (sec["reason"] if sec else (rep["reason"] if rep else "not downloaded")),
            viewers.get(rep["filing_id"], "") if rep and rep["filing_id"] else "",
            _tab(t) if sec and sec["path"] else "",
        ]
        labels = [old.get(t, {}).get(k) for k in LABEL_COLS]
        ws.append(info + labels)
        r = ws.max_row
        if info[7]:
            ws.cell(r, 8).hyperlink = info[7]
            ws.cell(r, 8).value = "open report"
            ws.cell(r, 8).font = Font(color="0563C1", underline="single")
        if info[8]:
            ws.cell(r, 9).hyperlink = Hyperlink(ref=ws.cell(r, 9).coordinate, location=f"'{info[8]}'!A1")
            ws.cell(r, 9).font = Font(color="0563C1", underline="single")

    n = ws.max_row
    first_label = len(INFO_COLS) + 1

    def col(name: str) -> str:
        return openpyxl.utils.get_column_letter(first_label + LABEL_COLS.index(name))

    for name, values in [("verdict", VERDICTS), ("supply chain", YES_NO), ("TPRM programme", YES_NO),
                         ("emerging risks", EMERGING)]:
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col(name)}2:{col(name)}{n}")

    head_fill, label_fill = PatternFill("solid", fgColor="D9D9D9"), PatternFill("solid", fgColor="FFF2CC")
    for i, cell in enumerate(ws[1], 1):
        cell.font = Font(bold=True)
        cell.fill = label_fill if i >= first_label else head_fill
    widths = [8, 30, 18, 10, 11, 9, 40, 14, 12, 16, 28, 50, 12, 14, 22, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column >= first_label)
    ws.freeze_panes = "C2"

    guide = wb.create_sheet("How to label")
    guide.column_dimensions["A"].width = 120
    for line in (config.PROJECT_DIR / "docs" / "labelling-guide.md").read_text(encoding="utf-8").splitlines():
        guide.append([line])
    themes = wb.create_sheet("Themes")
    themes.append(["Themes (type one or more into the themes column, separated by ; )"])
    for t in THEMES:
        themes.append([t])

    # One tab per company with its extracted section, so it can be read anywhere (phone included).
    for t in tickers:
        sec = con.execute("SELECT path FROM sections WHERE ticker = ? AND status = 'found'", (t,)).fetchone()
        if not sec:
            continue
        tab = wb.create_sheet(_tab(t))
        tab.column_dimensions["A"].width = 100
        tab.append([f"{companies.get(t, {}).get('name', t).title()}: extracted risk section"])
        tab["A1"].font = Font(bold=True)
        for line in Path(sec["path"]).read_text(encoding="utf-8").splitlines():
            tab.append([line[:32000]])

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return n - 1
