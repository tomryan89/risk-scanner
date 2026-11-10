# Refresh runbook

UK listed companies must publish their annual report within **4 months** of their financial year end, and most
have a 31 December year end. Good refresh windows:

| When | Picks up | Share of the list (Nov 2026) |
|---|---|---|
| **Mid–late May** | 31 December year ends (due by 30 April) | ~55%, incl. most large companies |
| **Mid August** | 31 March year ends (due by 31 July) | ~18% |
| November (optional) | 30 June and 30 September year ends | ~15% |

Leave two or three weeks after the deadline: filings.xbrl.org lags the official filing.

## 1. Update the company list (optional, once a year)

Listings change. Download the London Stock Exchange **Instrument list**
(`https://docs.londonstockexchange.com/reports/instruments/Instrument%20list.xlsx`) into
`data/raw/Instrument_list_YYYY-MM-DD.xlsx`, then:

```bash
python -m scanner companies          # rebuilds data/companies.csv
python -m scanner reports            # downloads reports for newly listed companies only
```

## 2. Find newer reports

```bash
python -m scanner refresh --dry-run  # what's newer on XBRL; downloads nothing
python -m scanner refresh            # downloads them; writes data/refresh_<date>.txt
```

Old report files are kept; `report_history` records old vs new year. The command also lists companies held from a
**company website, a manual PDF or a scan**: XBRL can't tell us if they have a newer report. For those, find the new
PDF (Claude Code agents can search the companies' investor-relations pages), update the row's `url` and `fy_end` in
`data/website_reports.csv` (a local file path is fine for PDFs saved by hand), then:

```bash
python -m scanner websites --tickers A,B,C --redo
```

## 3. Re-classify only what changed

```bash
python -m scanner refresh-classify --name 2027-05 --base final-2026-11 --add A,B,C
```

`--add` takes the website/manual tickers from step 2. For the changed companies it re-extracts the risk section,
has Haiku and Opus each classify it, sends companies with a missing/short section (or a "couldn't check") to Opus
on the whole report, breaks Haiku/Opus disagreements with Opus at high effort, then merges into `final-2027-05`
(every other company carried over from `--base`) and exports `output/results_final-2027-05.xlsx`. It uses the
Batch API (half price) and is resumable: re-run the same command after an interruption.

Cost guide: about $0.08–0.15 per changed company; a May refresh of ~260 companies ≈ $20–40. Add `--haiku-only`
to skip Opus entirely (Haiku classifies the sections and reads whole reports where needed; no second opinion or
tie-break): about $0.01–0.02 per company, so a May refresh ≈ $3–5, with somewhat less checking.

## 4. Scans

Image-only PDFs (no text layer) can be read by Opus as page images:

```python
from pathlib import Path
from scanner import scans
scans.classify_scan("TICKER", Path("report.pdf"), "report-2027-05", "2026-12-31", source_url=None)
```

Use the refresh's report run name (`report-<name>`) so `refresh-classify` picks it up.
