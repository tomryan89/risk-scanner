"""Turn a report into plain text lines: an ESEF package (inline XBRL XHTML inside a zip) or a PDF (Companies House).

Most UK ESEF reports are PDF-to-XHTML conversions: every text fragment is a positioned <div>/<span>, so we treat
block tags as line breaks and inline tags as nothing (replacing them with spaces splits words: "fact ors").
"""

import html
import re
import zipfile
from pathlib import Path

_BLOCK = re.compile(r"</?(?:div|p|br|tr|li|h[1-6]|table|section|article|td|th)\b[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|head)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_HIDDEN = re.compile(r"<ix:header\b.*?</ix:header\s*>", re.S | re.I)  # XBRL metadata, not report text
_TAG = re.compile(r"<[^>]+>")


def report_files(zip_path: Path) -> list[str]:
    """The human-readable report document(s) inside an ESEF package."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist()
                 if "/reports/" in n and n.lower().endswith((".xhtml", ".html", ".htm")) and "viewer" not in n.lower()]
    return sorted(names)


def zip_to_lines(zip_path: Path) -> list[str]:
    lines: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for name in report_files(zip_path):
            lines.extend(xhtml_to_lines(z.read(name).decode("utf-8", "replace")))
    return lines


def xhtml_to_lines(doc: str) -> list[str]:
    doc = _HIDDEN.sub(" ", _DROP.sub(" ", doc))
    doc = _BLOCK.sub("\n", doc)
    text = html.unescape(_TAG.sub("", doc)).replace(" ", " ")
    out = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if line:
            out.append(line)
    return out


def report_to_lines(path: Path) -> list[str]:
    """Any downloaded report: ESEF zip, PDF or a bare XHTML file."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return zip_to_lines(path)
    if suffix == ".pdf":
        return pdf_to_lines(path)
    return xhtml_to_lines(path.read_text(encoding="utf-8", errors="replace"))


def pdf_to_lines(path: Path) -> list[str]:
    import pymupdf

    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for raw in page.get_text("text").split("\n"):
                line = " ".join(raw.split())
                if line:
                    out.append(line)
    return out


def pdf_text_density(path: Path) -> float:
    """Average characters of text per page; scanned image PDFs come out near 0."""
    import pymupdf

    with pymupdf.open(path) as doc:
        return sum(len(p.get_text("text")) for p in doc) / max(len(doc), 1)
