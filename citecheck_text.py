#!/usr/bin/env python3
"""Verify citations in raw text from stdin → print the AuditReport as JSON to stdout.

Thin wrapper around the package's CitationChecker so serve-podcast can shell to it with the
assembled draft text (no DOCX export needed). Reads text on stdin, writes JSON on stdout.
Usage:  echo "<brief text>" | python3 citecheck_text.py
"""
import sys
import json
import tempfile
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))


def main() -> int:
    text = sys.stdin.read()
    if not text.strip():
        print(json.dumps({"error": "empty text"}))
        return 0
    try:
        from docx import Document
        from legal_citation_checker.pipeline import CitationChecker
    except Exception as e:  # pragma: no cover
        print(json.dumps({"error": f"import failed: {e}"}))
        return 0
    tmp = pathlib.Path(tempfile.mktemp(suffix=".docx"))
    try:
        doc = Document()
        for para in text.split("\n"):
            doc.add_paragraph(para)
        doc.save(tmp)
        report = CitationChecker(verbose=False).process_document(tmp)
        print(report.to_string(format="json"))
    except Exception as e:
        print(json.dumps({"error": f"check failed: {e}"}))
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
