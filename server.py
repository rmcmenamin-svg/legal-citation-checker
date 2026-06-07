#!/usr/bin/env python3
"""MCP server for legal citation verification."""

import sys
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent / "src"))
from legal_citation_checker.pipeline import CitationChecker

mcp = FastMCP("legal-citation-checker")


@mcp.tool()
def check_citations(file_path: str, output_format: str = "markdown") -> str:
    """Verify citation authenticity in a DOCX or PDF legal document.

    Extracts all case citations, checks each against CourtListener and Google
    Caselaw, and returns an audit report flagging any potential hallucinations.

    Args:
        file_path: Absolute path to a .docx or .pdf file.
        output_format: Report format — "markdown" (default), "json", or "html".
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"Error: file not found: {path}"
    if path.suffix.lower() not in (".docx", ".pdf"):
        return f"Error: unsupported file type '{path.suffix}' — use .docx or .pdf"
    if output_format not in ("markdown", "json", "html"):
        output_format = "markdown"

    try:
        checker = CitationChecker(verbose=False)
        report = checker.process_document(path)
        return report.to_string(format=output_format)
    except Exception as e:
        return f"Error processing document: {e}"


@mcp.tool()
def check_citations_text(text: str, output_format: str = "markdown") -> str:
    """Verify citations in raw text (paste a brief section directly).

    Useful when you don't have a file path — paste the text of a brief section
    and get back a citation audit report.

    Args:
        text: Raw legal text containing citations to verify.
        output_format: "markdown" (default), "json", or "html".
    """
    import tempfile
    import os

    try:
        from docx import Document
    except ImportError:
        return "Error: python-docx not installed"

    if output_format not in ("markdown", "json", "html"):
        output_format = "markdown"

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        doc = Document()
        for para in text.split("\n"):
            doc.add_paragraph(para)
        doc.save(tmp_path)

        checker = CitationChecker(verbose=False)
        report = checker.process_document(tmp_path)
        return report.to_string(format=output_format)
    except Exception as e:
        return f"Error: {e}"
    finally:
        tmp_path.unlink(missing_errors=True)


if __name__ == "__main__":
    mcp.run(transport="stdio")
