"""Audit report generation with multi-format export support."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List

from .models import CitationAudit


@dataclass
class AuditReport:
    """Serializable audit report with multi-format export support."""

    source_document: str
    generated_at: str
    processing_seconds: float
    citations: List[CitationAudit]
    notes: List[str] = field(default_factory=list)

    @property
    def total_citations(self) -> int:
        return len(self.citations)

    @property
    def verified_count(self) -> int:
        return len([c for c in self.citations if c.status.startswith("Verified")])

    @property
    def hallucination_count(self) -> int:
        return len([c for c in self.citations if c.status == "Potential Hallucination"])

    @property
    def needs_review_count(self) -> int:
        return len([c for c in self.citations if c.status == "Needs Review"])

    @property
    def skipped_count(self) -> int:
        return len([c for c in self.citations if c.status == "Skipped (Non-Case Citation)"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_document": self.source_document,
            "generated_at": self.generated_at,
            "processing_seconds": round(self.processing_seconds, 3),
            "summary": {
                "total_citations": self.total_citations,
                "verified": self.verified_count,
                "potential_hallucinations": self.hallucination_count,
                "needs_review": self.needs_review_count,
                "skipped": self.skipped_count,
            },
            "notes": self.notes,
            "citations": [citation.to_dict() for citation in self.citations],
        }

    def to_string(self, format: str = "markdown") -> str:
        fmt = format.lower().strip()
        if fmt == "json":
            return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        if fmt == "markdown":
            return self._to_markdown()
        if fmt == "html":
            return self._to_html()
        raise ValueError(f"Unsupported format: {format}")

    def save(self, path: Path, format: str = "markdown") -> None:
        path = Path(path)
        content = self.to_string(format=format)
        path.write_text(content, encoding="utf-8")

    def _to_markdown(self) -> str:
        lines: List[str] = []
        lines.append("# Legal Citation Checker Audit Report")
        lines.append("")
        lines.append(f"- Generated: {self.generated_at}")
        lines.append(f"- Source document: `{self.source_document}`")
        lines.append(f"- Processing time: {self.processing_seconds:.2f} seconds")
        summary_parts = [
            f"{self.total_citations} citations found",
            f"{self.verified_count} verified",
            f"{self.hallucination_count} potential hallucinations",
        ]
        if self.needs_review_count:
            summary_parts.append(f"{self.needs_review_count} needs review")
        if self.skipped_count:
            summary_parts.append(f"{self.skipped_count} skipped (non-case)")
        lines.append("- Summary: " + ", ".join(summary_parts))
        if self.notes:
            lines.append("- Notes: " + "; ".join(self.notes))
        lines.append("")

        if not self.citations:
            lines.append("No citations were extracted from this document.")
            return "\n".join(lines)

        # Executive summary: only show citations that need attention.
        flagged = [c for c in self.citations if c.status in ("Potential Hallucination", "Needs Review")]
        if flagged:
            lines.append("## Action Required")
            lines.append("")
            lines.append("The following citations could not be verified and need manual review:")
            lines.append("")
            lines.append("| # | Citation | Status | Context |")
            lines.append("| --- | --- | --- | --- |")
            for c in flagged:
                ctx = c.context[:80] + "..." if len(c.context) > 80 else c.context
                ctx = ctx.replace("|", "\\|")
                lines.append(f"| {c.index} | `{c.normalized_citation}` | {c.status} | {ctx} |")
            lines.append("")
        else:
            lines.append("## All Citations Verified")
            lines.append("")
            lines.append("No issues found. All extracted citations were verified against legal databases.")
            lines.append("")

        for citation in self.citations:
            lines.append(f"## Citation {citation.index}")
            lines.append(f"- Raw: `{citation.raw_citation}`")
            lines.append(f"- Bluebook normalized: `{citation.normalized_citation}`")
            lines.append(f"- Status: **{citation.status}**")
            lines.append(f"- Confidence: {citation.confidence}%")
            if citation.source:
                lines.append(f"- Source: {citation.source}")
            if citation.source_url:
                lines.append(f"- Source URL: {citation.source_url}")
            lines.append(f"- Citation type: {citation.citation_type}")
            lines.append(f"- Paragraph: {citation.paragraph_index if citation.paragraph_index is not None else 'Unknown'}")
            lines.append(f"- Context: {citation.context}")
            lines.append(f"- Evidence: {citation.evidence}")
            lines.append(f"- Search attempts: {len(citation.search_attempts)}")

            if citation.search_attempts:
                lines.append("")
                lines.append("| Source | Strategy | Query | Success | Results | URL |")
                lines.append("| --- | --- | --- | --- | --- | --- |")
                for attempt in citation.search_attempts:
                    esc = lambda s: str(s).replace("|", "\\|")
                    lines.append(
                        "| "
                        f"{esc(attempt.source)} | {esc(attempt.strategy)} | {esc(attempt.query)} | "
                        f"{'Yes' if attempt.success else 'No'} | {attempt.result_count} | "
                        f"{esc(attempt.url or '')} |"
                    )
            lines.append("")

        return "\n".join(lines)

    def _to_html(self) -> str:
        report = self.to_dict()
        rows = []
        for citation in self.citations:
            attempts_html = "".join(
                (
                    "<li>"
                    f"{html_escape(a.source)} / {html_escape(a.strategy)} / "
                    f"{html_escape(a.query)} / {'success' if a.success else 'failed'} "
                    f"({a.result_count})"
                    "</li>"
                )
                for a in citation.search_attempts
            )
            source_url_html = (
                f'<a href="{html_escape(citation.source_url)}">{html_escape(citation.source_url)}</a>'
                if citation.source_url
                else ""
            )
            rows.append(
                "<tr>"
                f"<td>{citation.index}</td>"
                f"<td><code>{html_escape(citation.raw_citation)}</code></td>"
                f"<td><code>{html_escape(citation.normalized_citation)}</code></td>"
                f"<td>{html_escape(citation.status)}</td>"
                f"<td>{citation.confidence}%</td>"
                f"<td>{html_escape(citation.source or '')}</td>"
                f"<td>{source_url_html}</td>"
                f"<td>{html_escape(citation.context)}</td>"
                f"<td><ul>{attempts_html}</ul></td>"
                "</tr>"
            )

        notes_html = "".join(f"<li>{html_escape(note)}</li>" for note in self.notes)
        return (
            "<!doctype html>"
            "<html><head><meta charset='utf-8'><title>Legal Citation Checker Audit Report</title>"
            "<style>body{font-family:Arial,sans-serif;padding:24px;}"
            "table{border-collapse:collapse;width:100%;margin-top:16px;}"
            "th,td{border:1px solid #ccc;padding:8px;text-align:left;}"
            "th{background:#f5f5f5;}"
            ".hallucination{background:#ffe0e0;}"
            ".verified{background:#e0ffe0;}"
            ".needs-review{background:#fff8e0;}"
            "</style></head><body>"
            "<h1>Legal Citation Checker Audit Report</h1>"
            f"<p>Generated: {html_escape(report['generated_at'])}</p>"
            f"<p>Source: <code>{html_escape(report['source_document'])}</code></p>"
            f"<p>Processing time: {report['processing_seconds']}s</p>"
            "<h2>Summary</h2>"
            f"<ul><li>Total citations: {report['summary']['total_citations']}</li>"
            f"<li>Verified: {report['summary']['verified']}</li>"
            f"<li>Potential hallucinations: {report['summary']['potential_hallucinations']}</li>"
            f"<li>Needs review: {report['summary']['needs_review']}</li>"
            f"<li>Skipped: {report['summary']['skipped']}</li></ul>"
            + (f"<h2>Notes</h2><ul>{notes_html}</ul>" if notes_html else "")
            + "<h2>Citations</h2>"
            "<table><thead><tr>"
            "<th>#</th><th>Raw</th><th>Normalized</th><th>Status</th>"
            "<th>Confidence</th><th>Source</th><th>URL</th><th>Context</th><th>Search Attempts</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></body></html>"
        )
