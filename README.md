# Principal Risks Scanner

Checks the latest annual report of every UK Main Market operating company for **third-party risk** (suppliers,
vendors, outsourcers, agents and other third parties; *not* supply chain risk) listed among its **principal risks**,
and writes one spreadsheet row per company: a verdict, the theme, and a word-for-word quote as evidence.

Verdicts: **yes** (a named principal risk is about third-party risk) · **passing mention** (third parties named as
a cause inside another principal risk) · **no** · **couldn't check** (no usable report). The rules are in
[`docs/labelling-guide.md`](docs/labelling-guide.md), which is also the model's instructions.

## How it works

| Step | Command | What it does |
|---|---|---|
| Company list | `companies` | Filters the LSE Instrument list to Main Market operating companies |
| Reports | `reports` | ISIN → LEI (GLEIF) → latest ESEF report from filings.xbrl.org |
| Gaps | `websites`, `companies-house` | Reports from company websites (links in `data/website_reports.csv`, manual PDFs allowed) |
| Risk section | `sections` | Finds the principal risks chapter in each report |
| Classify | `classify`, `batch` | Claude reads the section (or the whole report with `--mode report`) and answers in structured JSON |
| Combine | `merge` | Haiku + Opus agreement, Opus tie-breaks, whole-report reads where the section was bad |
| Output | `export` | `output/results_<run>.xlsx`, one row per company plus a summary tab |

Every quote is checked word for word against the report text, so invented quotes are flagged. Every step is
resumable, and Batch API job IDs are saved before polling.

## Setup

Python 3.12+ (built on 3.14).

```bash
python -m venv .venv            # or: uv venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then add your Anthropic API key
.venv/bin/python -m scanner check
```

`.env` holds `ANTHROPIC_API_KEY` (required) and optionally `COMPANIES_HOUSE_API_KEY`, `SCANNER_DATA_DIR`,
`SCANNER_OUTPUT_DIR` and `SCANNER_REPORTS_DIR` (where report downloads go; set this, as the default is a path on the
original machine).

## A full run

```bash
python -m scanner companies                     # needs the LSE Instrument list in data/raw/
python -m scanner reports
python -m scanner websites                      # optional: fill gaps from data/website_reports.csv
python -m scanner sections
python -m scanner batch submit --run full       # Haiku, half price via the Batch API
python -m scanner batch wait --run full
python -m scanner export --run full
```

Cost guide (November 2026): Haiku on ~450 risk sections ≈ $0.50; Opus on the same ≈ $15; Opus reading the whole
front half of a report ≈ $0.30–0.45 each.

## Be polite

Requests are throttled (one every 3 seconds) with a generic user agent. The FCA National Storage Mechanism's terms
forbid scripted access, so it is never used. Sites that block scripts are left alone; save those PDFs by hand.
