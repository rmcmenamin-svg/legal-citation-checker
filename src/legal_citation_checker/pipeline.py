"""Core citation checking pipeline for Phase 1.

Phase 1 scope:
- DOCX-only text extraction
- Citation extraction via eyecite
- Bluebook-style normalization
- Citation authenticity verification (CourtListener primary)
- Audit report generation (markdown/html/json)
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime
    requests = None  # type: ignore

# Citation types that should be skipped (not verifiable against case law databases).
_SKIP_CITATION_TYPES = frozenset({
    "NonopinionCitation",
    "IdCitation",
    "SupraCitation",
    "ShortCaseCitation",
    "UnknownCitation",
})

# Regex patterns for statutes, regulations, and other non-case citations.
_STATUTE_PATTERNS = [
    re.compile(r"\b\d+\s+U\.?S\.?C\.?\s*(§|[Ss]ection)?\s*\d+", re.IGNORECASE),
    re.compile(r"\b\d+\s+C\.?F\.?R\.?\s*(§|[Ss]ection|[Pp]art)?\s*\d+", re.IGNORECASE),
    re.compile(r"\bPub\.?\s*L\.?\s*No\.?\s*\d+", re.IGNORECASE),
    re.compile(r"\b[A-Z][a-z]+\.?\s*(Rev\.?\s*)?((Ann\.?\s*)?(Code|Stat|Laws|Gen\.?\s*Stat))", re.IGNORECASE),
]

# Regex to strip pincites: "347 U.S. 483, 495" → "347 U.S. 483"
_PINCITE_PATTERN = re.compile(r"^(.+?\d+)\s*,\s*\d+(?:\s*[-–]\s*\d+)?$")

# Regex to detect Westlaw citations: "2025 WL 2192378"
_WESTLAW_PATTERN = re.compile(r"^\d{4}\s+WL\s+\d+$", re.IGNORECASE)

# CourtListener search API (the /opinions/ endpoint requires auth, /search/ does not).
COURTLISTENER_SEARCH_BASE = "https://www.courtlistener.com/api/rest/v4/search/"


@dataclass
class ParagraphSpan:
    """Character offsets for a paragraph within flattened DOCX text."""

    index: int
    text: str
    start: int
    end: int


@dataclass
class DocumentText:
    """Flattened DOCX content plus paragraph offsets."""

    full_text: str
    paragraphs: List[ParagraphSpan]


@dataclass
class SearchAttempt:
    """One verification attempt against a source/strategy."""

    source: str
    strategy: str
    query: str
    success: bool
    result_count: int = 0
    url: Optional[str] = None
    details: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationDecision:
    """Outcome of citation verification."""

    status: str
    confidence: int
    source: Optional[str] = None
    source_url: Optional[str] = None
    evidence: str = ""
    search_attempts: List[SearchAttempt] = field(default_factory=list)

    def clone(self) -> "VerificationDecision":
        return VerificationDecision(
            status=self.status,
            confidence=self.confidence,
            source=self.source,
            source_url=self.source_url,
            evidence=self.evidence,
            search_attempts=[SearchAttempt(**attempt.to_dict()) for attempt in self.search_attempts],
        )


@dataclass
class CitationAudit:
    """Per-citation audit details for report output."""

    index: int
    raw_citation: str
    normalized_citation: str
    citation_type: str
    context: str
    paragraph_index: Optional[int]
    metadata: Dict[str, Any]
    bluebook_normalized: bool
    status: str
    confidence: int
    source: Optional[str]
    source_url: Optional[str]
    evidence: str
    search_attempts: List[SearchAttempt] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["search_attempts"] = [attempt.to_dict() for attempt in self.search_attempts]
        return data


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
                    lines.append(
                        "| "
                        f"{attempt.source} | {attempt.strategy} | {attempt.query} | "
                        f"{'Yes' if attempt.success else 'No'} | {attempt.result_count} | "
                        f"{attempt.url or ''} |"
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
            "table{border-collapse:collapse;width:100%;}"
            "th,td{border:1px solid #ccc;padding:8px;vertical-align:top;}"
            "th{background:#f5f5f5;text-align:left;}code{background:#f0f0f0;padding:2px 4px;}"
            "</style></head><body>"
            "<h1>Legal Citation Checker Audit Report</h1>"
            f"<p><strong>Generated:</strong> {html_escape(report['generated_at'])}</p>"
            f"<p><strong>Source document:</strong> {html_escape(report['source_document'])}</p>"
            f"<p><strong>Processing time:</strong> {self.processing_seconds:.2f} seconds</p>"
            f"<p><strong>Summary:</strong> {self.total_citations} citations found, "
            f"{self.verified_count} verified, {self.hallucination_count} potential hallucinations"
            f"{f', {self.needs_review_count} needs review' if self.needs_review_count else ''}"
            f"{f', {self.skipped_count} skipped' if self.skipped_count else ''}</p>"
            f"<h2>Notes</h2><ul>{notes_html}</ul>"
            "<h2>Citations</h2>"
            "<table><thead><tr>"
            "<th>#</th><th>Raw</th><th>Normalized</th><th>Status</th><th>Confidence</th>"
            "<th>Source</th><th>URL</th><th>Context</th><th>Search Attempts</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></body></html>"
        )


@dataclass
class ExtractedCitation:
    """Intermediate citation object before verification."""

    index: int
    raw_citation: str
    normalized_citation: str
    citation_type: str
    context: str
    paragraph_index: Optional[int]
    metadata: Dict[str, Any]
    bluebook_normalized: bool


class CitationChecker:
    """Phase 1 pipeline orchestrator."""

    def __init__(
        self,
        verbose: bool = False,
        request_timeout: float = 8.0,
        user_agent: str = "legal-citation-checker/0.1",
        max_workers: int = 4,
    ) -> None:
        self.verbose = verbose
        self.request_timeout = request_timeout
        self.user_agent = user_agent
        self.max_workers = max_workers
        self._verification_cache: Dict[str, VerificationDecision] = {}
        self._reporter_aliases: Optional[Dict[str, str]] = None

        self._session = None
        if requests is not None:
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
            self._session = session

    def process_document(self, input_file: Path) -> AuditReport:
        """Run the complete pipeline and return a report object."""
        started = time.perf_counter()
        path = Path(input_file)

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".docx":
            self._log(f"Extracting DOCX text from {path}")
            document_text = self._extract_docx_text(path)
        elif suffix == ".pdf":
            self._log(f"Extracting PDF text from {path}")
            document_text = self._extract_pdf_text(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}. Supported: .docx, .pdf")

        self._log("Extracting citations with eyecite")
        extracted_citations = self._extract_citations(document_text)

        self._log(f"Running verification pipeline for {len(extracted_citations)} citation(s)")

        # Build list of citations needing verification (check cache first).
        # Deduplicate by base citation (strip pincites) so "347 U.S. 483, 495"
        # shares results with "347 U.S. 483".
        to_verify: List[Tuple[ExtractedCitation, str]] = []
        cached_decisions: Dict[int, VerificationDecision] = {}
        seen_keys: set = set()
        for citation in extracted_citations:
            base = self._strip_pincite(citation.normalized_citation or citation.raw_citation)
            cache_key = self._cache_key(base)
            if cache_key in self._verification_cache:
                cached_decisions[citation.index] = self._verification_cache[cache_key].clone()
                self._log(f"Cache hit for citation {citation.index}: {citation.normalized_citation}")
            elif cache_key in seen_keys:
                # Another citation with the same base is already queued — skip duplicate.
                self._log(f"Dedup: citation {citation.index} ({base}) already queued")
                to_verify.append((citation, cache_key))
            else:
                seen_keys.add(cache_key)
                to_verify.append((citation, cache_key))

        # Verify uncached citations concurrently.
        verified_decisions: Dict[int, VerificationDecision] = {}
        if to_verify and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(to_verify))) as executor:
                future_map = {
                    executor.submit(self._verify_citation, cit): (cit, key)
                    for cit, key in to_verify
                }
                for future in as_completed(future_map):
                    cit, key = future_map[future]
                    try:
                        decision = future.result()
                    except Exception as exc:
                        decision = VerificationDecision(
                            status="Needs Review",
                            confidence=0,
                            evidence=f"Verification failed with error: {exc}",
                        )
                    self._verification_cache[key] = decision.clone()
                    verified_decisions[cit.index] = decision
        else:
            for cit, key in to_verify:
                decision = self._verify_citation(cit)
                self._verification_cache[key] = decision.clone()
                verified_decisions[cit.index] = decision

        # Assemble audit results in original order.
        audited_citations: List[CitationAudit] = []
        for citation in extracted_citations:
            decision = cached_decisions.get(citation.index) or verified_decisions[citation.index]
            audited_citations.append(
                CitationAudit(
                    index=citation.index,
                    raw_citation=citation.raw_citation,
                    normalized_citation=citation.normalized_citation,
                    citation_type=citation.citation_type,
                    context=citation.context,
                    paragraph_index=citation.paragraph_index,
                    metadata=citation.metadata,
                    bluebook_normalized=citation.bluebook_normalized,
                    status=decision.status,
                    confidence=decision.confidence,
                    source=decision.source,
                    source_url=decision.source_url,
                    evidence=decision.evidence,
                    search_attempts=decision.search_attempts,
                )
            )

        elapsed = time.perf_counter() - started
        notes: List[str] = []
        if not extracted_citations:
            notes.append("No citations detected by eyecite in document text.")
        if self._session is None:
            notes.append("requests is unavailable; online verification attempts cannot execute.")

        return AuditReport(
            source_document=str(path),
            generated_at=datetime.now(timezone.utc).isoformat(),
            processing_seconds=elapsed,
            citations=audited_citations,
            notes=notes,
        )

    def _extract_docx_text(self, path: Path) -> DocumentText:
        Document = self._import_python_docx_document()
        doc = Document(str(path))

        paragraphs: List[ParagraphSpan] = []
        chunks: List[str] = []
        cursor = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            text = (paragraph.text or "").strip()
            if not text:
                continue

            if chunks:
                chunks.append("\n\n")
                cursor += 2

            start = cursor
            chunks.append(text)
            cursor += len(text)
            end = cursor

            paragraphs.append(
                ParagraphSpan(
                    index=paragraph_index,
                    text=text,
                    start=start,
                    end=end,
                )
            )

        full_text = "".join(chunks)
        return DocumentText(full_text=full_text, paragraphs=paragraphs)

    def _extract_pdf_text(self, path: Path) -> DocumentText:
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except ImportError:
                raise RuntimeError(
                    "PDF support requires pdfplumber or PyPDF2. "
                    "Install with: pip install pdfplumber"
                )
            return self._extract_pdf_text_pypdf2(path, PdfReader)
        return self._extract_pdf_text_pdfplumber(path, pdfplumber)

    def _extract_pdf_text_pdfplumber(self, path: Path, pdfplumber: Any) -> DocumentText:
        paragraphs: List[ParagraphSpan] = []
        chunks: List[str] = []
        cursor = 0

        with pdfplumber.open(str(path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                if not text:
                    continue

                if chunks:
                    chunks.append("\n\n")
                    cursor += 2

                start = cursor
                chunks.append(text)
                cursor += len(text)

                paragraphs.append(
                    ParagraphSpan(index=page_num, text=text, start=start, end=cursor)
                )

        return DocumentText(full_text="".join(chunks), paragraphs=paragraphs)

    def _extract_pdf_text_pypdf2(self, path: Path, PdfReader: Any) -> DocumentText:
        paragraphs: List[ParagraphSpan] = []
        chunks: List[str] = []
        cursor = 0

        reader = PdfReader(str(path))
        for page_num, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue

            if chunks:
                chunks.append("\n\n")
                cursor += 2

            start = cursor
            chunks.append(text)
            cursor += len(text)

            paragraphs.append(
                ParagraphSpan(index=page_num, text=text, start=start, end=cursor)
            )

        return DocumentText(full_text="".join(chunks), paragraphs=paragraphs)

    def _extract_citations(self, document_text: DocumentText) -> List[ExtractedCitation]:
        get_citations = self._import_eyecite_get_citations()

        if not document_text.full_text.strip():
            return []

        citations: List[ExtractedCitation] = []
        extracted = get_citations(document_text.full_text)

        for i, citation_obj in enumerate(extracted, start=1):
            citation_type_name = type(citation_obj).__name__

            # Skip non-case citation types (Id., Supra, short cites).
            if citation_type_name in _SKIP_CITATION_TYPES:
                self._log(f"Skipping {citation_type_name}: {citation_obj}")
                continue

            span = self._citation_span(citation_obj)
            raw_citation = self._raw_citation_text(citation_obj, document_text.full_text, span)

            # Skip bare symbols and very short non-citation text.
            stripped = raw_citation.strip(" §.,;:()")
            if len(stripped) < 3:
                self._log(f"Skipping too-short extraction: {raw_citation!r}")
                continue

            # Skip statute/regulation patterns.
            if self._is_statute_or_regulation(raw_citation):
                self._log(f"Skipping statute/regulation: {raw_citation}")
                continue

            metadata = self._citation_metadata(citation_obj)
            normalized, changed = self._normalize_bluebook(raw_citation, metadata)
            paragraph_index = self._paragraph_for_span(document_text.paragraphs, span)
            context = self._citation_context(document_text, span)

            citations.append(
                ExtractedCitation(
                    index=len(citations) + 1,
                    raw_citation=raw_citation,
                    normalized_citation=normalized,
                    citation_type=citation_type_name,
                    context=context,
                    paragraph_index=paragraph_index,
                    metadata=metadata,
                    bluebook_normalized=changed,
                )
            )

        return citations

    @staticmethod
    def _is_statute_or_regulation(citation_text: str) -> bool:
        return any(pattern.search(citation_text) for pattern in _STATUTE_PATTERNS)

    def _normalize_bluebook(self, citation_text: str, metadata: Dict[str, Any]) -> Tuple[str, bool]:
        original = citation_text or ""
        normalized = original

        normalized = normalized.replace("\u00a0", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Normalize section symbols and spacing.
        normalized = re.sub(r"\b[Ss]ection\s+", "§ ", normalized)
        normalized = re.sub(r"§\s*", "§ ", normalized)

        # Canonicalize the common case-name separator.
        normalized = re.sub(r"\sv(?!\.)\s", " v. ", normalized)

        # Normalize punctuation spacing.
        normalized = re.sub(r"\s*,\s*", ", ", normalized)
        normalized = re.sub(r"\s*\(\s*", " (", normalized)
        normalized = re.sub(r"\s*\)\s*", ") ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Reporter abbreviation cleanup when reporters-db is available.
        normalized = self._normalize_reporter_abbreviation(normalized)

        # Optional external Bluebook formatter if present in environment.
        normalized = self._apply_external_bluebook_formatter(normalized)

        # Ensure trailing spaces/punctuation are standardized.
        normalized = normalized.rstrip(" ;")

        if not normalized:
            normalized = original

        changed = normalized != original
        metadata["bluebook_normalized"] = changed
        return normalized, changed

    def _verify_citation(self, citation: ExtractedCitation) -> VerificationDecision:
        attempts: List[SearchAttempt] = []

        # Westlaw citations can't be verified against free databases.
        if _WESTLAW_PATTERN.match(citation.normalized_citation.strip()):
            return VerificationDecision(
                status="Needs Review",
                confidence=0,
                source=None,
                source_url=None,
                evidence="Westlaw (WL) citations cannot be verified against free legal databases. "
                         "Manual verification via Westlaw required.",
                search_attempts=attempts,
            )

        # Step 1: CourtListener API (primary)
        decision = self._verify_with_courtlistener(citation, attempts)
        if decision is not None:
            return decision

        # Step 2: CourtListener second-tier (alternate queries)
        decision = self._verify_with_courtlistener_citation_lookup(citation, attempts)
        if decision is not None:
            return decision

        # Step 3: Additional secondary source fallback(s)
        decision = self._verify_with_secondary_sources(citation, attempts)
        if decision is not None:
            return decision

        # Step 4: Check if failures were due to network/API issues vs. real "not found".
        # If every single attempt had an error (network timeout, HTTP error, etc.),
        # we can't confidently call it a hallucination — flag for human review.
        all_errored = all(a.error is not None for a in attempts if a.details != "Skipped due to missing query parameters")
        non_skipped = [a for a in attempts if a.details != "Skipped due to missing query parameters"]

        if all_errored and non_skipped:
            return VerificationDecision(
                status="Needs Review",
                confidence=0,
                source=None,
                source_url=None,
                evidence="All verification sources returned errors (network/API issues). "
                         "Cannot determine if citation is valid or fabricated. Manual review required.",
                search_attempts=attempts,
            )

        # Step 5: Hallucination declaration — at least some sources responded but none matched.
        confidence = self._hallucination_confidence(len(attempts))
        evidence = self._build_failure_evidence(attempts)
        return VerificationDecision(
            status="Potential Hallucination",
            confidence=confidence,
            source=None,
            source_url=None,
            evidence=evidence,
            search_attempts=attempts,
        )

    def _verify_with_courtlistener(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        # Strip pincite for matching: "347 U.S. 483, 495" → "347 U.S. 483"
        base_citation = self._strip_pincite(citation.normalized_citation)

        strategies = [
            ("citation_search", {"q": f'citation:"{base_citation}"', "type": "o"}),
            ("citation_no_periods", {"q": f'citation:"{base_citation.replace(".", "")}"', "type": "o"}),
            ("broad_search", {"q": self._build_broad_query(citation), "type": "o"}),
        ]

        for strategy, params in strategies:
            query = params.get("q", "")
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            match_url = None
            result_count = 0
            success = False
            details = None

            if data is not None:
                result_count = self._count_results(data)
                matched_result = self._match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = self._extract_result_url(matched_result, base="https://www.courtlistener.com")
                    details = "Matched by citation/reporter metadata"
                else:
                    details = f"No matching result in {result_count} candidates"

            attempts.append(
                SearchAttempt(
                    source="CourtListener",
                    strategy=strategy,
                    query=query,
                    success=success,
                    result_count=result_count,
                    url=match_url or url,
                    details=details,
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (CourtListener)",
                    confidence=95,
                    source="CourtListener",
                    source_url=match_url or url,
                    evidence=f"CourtListener {strategy} strategy returned a matching citation.",
                    search_attempts=attempts,
                )

        return None

    @staticmethod
    def _strip_pincite(citation: str) -> str:
        m = _PINCITE_PATTERN.match(citation)
        return m.group(1).strip() if m else citation

    def _verify_with_courtlistener_citation_lookup(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Second-tier: try CourtListener citation-specific endpoint and alternate queries."""
        base_citation = self._strip_pincite(citation.normalized_citation)
        case_name = self._case_name_from_metadata(citation.metadata)
        meta_year = str(citation.metadata.get("year") or "")

        strategies = [
            ("cl_citation_exact", {"q": f'"{base_citation}"', "type": "o"}),
            ("cl_name_citation", {"q": f'{case_name} "{base_citation}"', "type": "o"} if case_name else None),
            ("cl_reporter_triplet", self._build_triplet_query(citation)),
        ]

        for strategy, params in strategies:
            if params is None:
                continue
            query = params.get("q", "") if isinstance(params, dict) else ""
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            match_url = None
            result_count = 0
            success = False
            details = None

            if data is not None:
                result_count = self._count_results(data)
                matched_result = self._match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = self._extract_result_url(matched_result, base="https://www.courtlistener.com")
                    details = "Matched via second-tier CourtListener search"

            attempts.append(
                SearchAttempt(
                    source="CourtListener (tier 2)",
                    strategy=strategy,
                    query=query,
                    success=success,
                    result_count=result_count,
                    url=match_url or url,
                    details=details or f"No match in {result_count} results",
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (CourtListener)",
                    confidence=90,
                    source="CourtListener",
                    source_url=match_url or url,
                    evidence=f"CourtListener tier-2 {strategy} strategy returned a match.",
                    search_attempts=attempts,
                )

        return None

    def _build_triplet_query(self, citation: ExtractedCitation) -> Optional[Dict[str, str]]:
        triplet = self._reporter_triplet(citation.normalized_citation)
        if not triplet:
            return None
        volume, reporter, page = triplet
        return {"q": f"{volume} {reporter} {page}", "type": "o"}

    def _verify_with_secondary_sources(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Third tier: CourtListener cluster search + relaxed matching."""
        base_citation = self._strip_pincite(citation.normalized_citation)
        case_name = self._case_name_from_metadata(citation.metadata)
        meta_year = str(citation.metadata.get("year") or "")

        # Strategy 1: search by just the volume/reporter/page with year filter.
        triplet = self._reporter_triplet(base_citation)
        if triplet:
            volume, _reporter_canon, page = triplet
            raw_reporter = self._raw_reporter_from_citation(base_citation)
            query_str = f'"{volume} {raw_reporter} {page}"'
            if meta_year:
                query_str += f" filed_after:{int(meta_year) - 1}-01-01 filed_before:{int(meta_year) + 1}-12-31"
            params = {"q": query_str, "type": "o"}
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            result_count = self._count_results(data) if data else 0
            success = False
            match_url = None

            if data and result_count > 0:
                # With an exact quoted triplet + year, any result is a strong match.
                results = data.get("results", [])
                if results and isinstance(results, list) and isinstance(results[0], dict):
                    success = True
                    match_url = self._extract_result_url(results[0], base="https://www.courtlistener.com")

            attempts.append(
                SearchAttempt(
                    source="CourtListener (tier 3)",
                    strategy="exact_triplet_year",
                    query=query_str,
                    success=success,
                    result_count=result_count,
                    url=match_url or url,
                    details="Matched via exact triplet + year" if success else f"No match in {result_count} results",
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (CourtListener)",
                    confidence=85,
                    source="CourtListener",
                    source_url=match_url or url,
                    evidence="Exact reporter triplet with year filter matched.",
                    search_attempts=attempts,
                )

        # Strategy 2: case name + year search.
        if case_name and meta_year:
            query_str = f'"{case_name}" filed_after:{int(meta_year) - 1}-01-01 filed_before:{int(meta_year) + 1}-12-31'
            params = {"q": query_str, "type": "o"}
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            result_count = self._count_results(data) if data else 0
            success = False
            match_url = None

            if data and result_count > 0 and result_count <= 50:
                results = data.get("results", [])
                if results and isinstance(results, list) and isinstance(results[0], dict):
                    success = True
                    match_url = self._extract_result_url(results[0], base="https://www.courtlistener.com")

            attempts.append(
                SearchAttempt(
                    source="CourtListener (tier 3)",
                    strategy="name_year",
                    query=query_str,
                    success=success,
                    result_count=result_count,
                    url=match_url or url,
                    details="Matched via case name + year" if success else f"No match in {result_count} results",
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (CourtListener)",
                    confidence=80,
                    source="CourtListener",
                    source_url=match_url or url,
                    evidence=f"Case name + year search matched ({result_count} results).",
                    search_attempts=attempts,
                )

        return None

    @staticmethod
    def _raw_reporter_from_citation(citation: str) -> str:
        """Extract the reporter string as-is (with periods) from a citation like '56 Cal. 2d 407'."""
        m = re.search(r"\b\d{1,4}\s+(.+?)\s+\d{1,5}\b", citation)
        return m.group(1).strip() if m else ""


    def _http_get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        if self._session is None:
            return None, None, "requests is not installed"

        try:
            response = self._session.get(url, params=params, timeout=self.request_timeout)
        except Exception as exc:
            return None, None, str(exc)

        request_url = getattr(response, "url", url)

        if response.status_code >= 400:
            return None, request_url, f"HTTP {response.status_code}"

        try:
            data = response.json()
        except Exception as exc:
            return None, request_url, f"Invalid JSON response: {exc}"

        if isinstance(data, dict):
            return data, request_url, None

        # Normalize list responses into dict shape for internal handling.
        if isinstance(data, list):
            return {"count": len(data), "results": data}, request_url, None

        return None, request_url, "Unexpected response type"

    def _count_results(self, data: Dict[str, Any]) -> int:
        count = data.get("count")
        if isinstance(count, int):
            return count

        results = data.get("results")
        if isinstance(results, list):
            return len(results)

        return 0

    def _match_courtlistener_result(
        self,
        citation: ExtractedCitation,
        data: Dict[str, Any],
        base_citation: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        candidates = data.get("results")
        if not isinstance(candidates, list):
            return None

        target_text = base_citation or citation.normalized_citation
        normalized_target = self._canonical_text(target_text)
        target_triplet = self._reporter_triplet(target_text)
        meta_name = self._case_name_from_metadata(citation.metadata)
        meta_year = str(citation.metadata.get("year") or "")

        for result in candidates:
            if not isinstance(result, dict):
                continue

            # Check citation fields (varies by API response shape).
            result_citations = (
                result.get("citation")
                or result.get("citations")
                or result.get("citeCount")  # sometimes nested
                or []
            )
            if isinstance(result_citations, str):
                result_citations = [result_citations]
            if isinstance(result_citations, list):
                for value in result_citations:
                    cite_str = value if isinstance(value, str) else (value.get("cite", "") if isinstance(value, dict) else "")
                    if not cite_str:
                        continue
                    if self._canonical_text(cite_str) == normalized_target:
                        return result
                    if target_triplet and self._triplet_match(cite_str, target_triplet):
                        return result

            # Check if the citation appears anywhere in the snippet/text fields.
            for text_field in ("snippet", "text", "plain_text", "html"):
                text_value = result.get(text_field, "")
                if isinstance(text_value, str) and target_text in text_value:
                    return result

            # Triplet match against caseName or cluster citation fields.
            case_name = str(result.get("caseName") or result.get("case_name") or result.get("caseNameFull") or "")
            date_filed = str(result.get("dateFiled") or result.get("date_filed") or result.get("dateArgued") or "")

            # Check if reporter triplet appears in the result's cluster/citation info.
            if target_triplet:
                cluster_uri = str(result.get("cluster") or result.get("cluster_id") or "")
                # Also check if the canonical citation text appears in case name field (sometimes CL embeds it).
                for field_name in ("caseName", "case_name", "caseNameFull"):
                    val = str(result.get(field_name, ""))
                    if target_triplet and self._triplet_match(val, target_triplet):
                        return result

            # Fallback: name/year match — require word-boundary match, not substring.
            if meta_name and case_name:
                canonical_meta = self._canonical_text(meta_name)
                canonical_case = self._canonical_text(case_name)
                # Require the full meta name to appear as whole words in the case name.
                if canonical_meta and re.search(r"\b" + re.escape(canonical_meta) + r"\b", canonical_case):
                    if not meta_year or meta_year in date_filed:
                        return result

        return None


    def _extract_result_url(self, result: Any, base: str) -> Optional[str]:
        if isinstance(result, dict):
            for key in (
                "absolute_url",
                "frontend_url",
                "url",
                "case_url",
                "resource_uri",
                "id",
            ):
                value = result.get(key)
                if isinstance(value, str) and value:
                    if value.startswith("http"):
                        return value
                    if base and value.startswith("/"):
                        return base.rstrip("/") + value
                    if base and key == "id" and value.isdigit():
                        return f"{base.rstrip('/')}/opinion/{value}/"

        if isinstance(result, str):
            return result

        return None

    def _citation_span(self, citation_obj: Any) -> Optional[Tuple[int, int]]:
        for attr in ("full_span", "span"):
            value = getattr(citation_obj, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if (
                isinstance(value, tuple)
                and len(value) == 2
                and all(isinstance(v, int) for v in value)
                and value[0] >= 0
                and value[1] >= value[0]
            ):
                return value
        return None

    def _raw_citation_text(
        self,
        citation_obj: Any,
        full_text: str,
        span: Optional[Tuple[int, int]],
    ) -> str:
        for attr in ("corrected_citation", "matched_text", "text"):
            value = getattr(citation_obj, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if isinstance(value, str) and value.strip():
                return value.strip()

        if span is not None:
            start, end = span
            snippet = full_text[start:end].strip()
            if snippet:
                return snippet

        fallback = str(citation_obj).strip()
        return fallback if fallback else "<unknown citation>"

    def _citation_metadata(self, citation_obj: Any) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}

        raw_meta = getattr(citation_obj, "metadata", None)
        if raw_meta is not None:
            if isinstance(raw_meta, dict):
                for key, value in raw_meta.items():
                    self._set_serializable(metadata, str(key), value)
            else:
                for key in dir(raw_meta):
                    if key.startswith("_"):
                        continue
                    try:
                        value = getattr(raw_meta, key)
                    except Exception:
                        continue
                    if callable(value):
                        continue
                    self._set_serializable(metadata, key, value)

        for attr in (
            "year",
            "court",
            "plaintiff",
            "defendant",
            "volume",
            "reporter",
            "page",
        ):
            if attr in metadata:
                continue
            try:
                value = getattr(citation_obj, attr)
            except Exception:
                value = None
            self._set_serializable(metadata, attr, value)

        return metadata

    def _set_serializable(self, target: Dict[str, Any], key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (str, int, float, bool)):
            target[key] = value
            return
        if isinstance(value, list):
            serializable = [item for item in value if isinstance(item, (str, int, float, bool))]
            if serializable:
                target[key] = serializable
            return

        target[key] = str(value)

    def _paragraph_for_span(
        self,
        paragraphs: List[ParagraphSpan],
        span: Optional[Tuple[int, int]],
    ) -> Optional[int]:
        if span is None:
            return None

        start, _ = span
        for paragraph in paragraphs:
            if paragraph.start <= start < paragraph.end:
                return paragraph.index
        return None

    def _citation_context(
        self,
        document_text: DocumentText,
        span: Optional[Tuple[int, int]],
        radius: int = 140,
    ) -> str:
        if not document_text.full_text:
            return ""

        if span is None:
            first_para = document_text.paragraphs[0].text if document_text.paragraphs else ""
            return first_para[: radius * 2]

        start, end = span
        left = max(0, start - radius)
        right = min(len(document_text.full_text), end + radius)
        snippet = document_text.full_text[left:right]
        return re.sub(r"\s+", " ", snippet).strip()

    def _build_broad_query(self, citation: ExtractedCitation) -> str:
        case_name = self._case_name_from_metadata(citation.metadata)
        year = str(citation.metadata.get("year") or "")
        parts = [part for part in [case_name, citation.normalized_citation, year] if part]
        if not parts:
            return citation.normalized_citation
        return " ".join(parts)

    def _query_full_case_court_year(self, citation: ExtractedCitation) -> str:
        case_name = self._case_name_from_metadata(citation.metadata)
        court = str(citation.metadata.get("court") or "")
        year = str(citation.metadata.get("year") or "")
        parts = [part for part in [case_name, court, year] if part]
        return " ".join(parts) if parts else citation.normalized_citation

    def _query_parties_reporter_page(self, citation: ExtractedCitation) -> str:
        plaintiff = str(citation.metadata.get("plaintiff") or "")
        defendant = str(citation.metadata.get("defendant") or "")
        triplet = self._reporter_triplet(citation.normalized_citation)
        triplet_text = " ".join(triplet) if triplet else citation.normalized_citation
        parts = [part for part in [plaintiff, defendant, triplet_text] if part]
        return " ".join(parts) if parts else citation.normalized_citation

    def _case_name_from_metadata(self, metadata: Dict[str, Any]) -> str:
        plaintiff = str(metadata.get("plaintiff") or "").strip()
        defendant = str(metadata.get("defendant") or "").strip()
        if plaintiff and defendant:
            return f"{plaintiff} v. {defendant}"

        for key in ("case_name", "name", "party_names"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    def _normalize_reporter_abbreviation(self, citation: str) -> str:
        aliases = self._load_reporter_aliases()
        if not aliases:
            return citation

        pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")

        def replace(match: re.Match[str]) -> str:
            volume = match.group(1)
            reporter = match.group(2).strip()
            page = match.group(3)
            key = self._canonical_text(reporter)
            canonical = aliases.get(key)
            if not canonical:
                return match.group(0)
            return f"{volume} {canonical} {page}"

        return pattern.sub(replace, citation)

    def _load_reporter_aliases(self) -> Dict[str, str]:
        if self._reporter_aliases is not None:
            return self._reporter_aliases

        aliases: Dict[str, str] = {}
        try:
            from reporters_db import REPORTERS  # type: ignore
        except Exception:
            self._reporter_aliases = aliases
            return aliases

        if isinstance(REPORTERS, dict):
            for canonical, entries in REPORTERS.items():
                if not isinstance(canonical, str):
                    continue
                canonical_key = self._canonical_text(canonical)
                aliases[canonical_key] = canonical

                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        name = entry.get("name")
                        if isinstance(name, str):
                            aliases[self._canonical_text(name)] = canonical
                        variations = entry.get("variations")
                        if isinstance(variations, dict):
                            for value in variations.values():
                                if isinstance(value, list):
                                    for item in value:
                                        if isinstance(item, str):
                                            aliases[self._canonical_text(item)] = canonical
                                elif isinstance(value, str):
                                    aliases[self._canonical_text(value)] = canonical

        self._reporter_aliases = aliases
        return aliases

    def _apply_external_bluebook_formatter(self, citation: str) -> str:
        module_candidates = [
            "bluebook_cite",
            "bluebookcite",
        ]
        function_candidates = [
            "format_citation",
            "format",
            "normalize_citation",
        ]

        for module_name in module_candidates:
            try:
                module = __import__(module_name)
            except Exception:
                continue

            for fn_name in function_candidates:
                fn = getattr(module, fn_name, None)
                if not callable(fn):
                    continue
                try:
                    result = fn(citation)
                except Exception:
                    continue
                if isinstance(result, str) and result.strip():
                    return result.strip()

        return citation

    def _hallucination_confidence(self, attempt_count: int) -> int:
        if attempt_count >= 6:
            return 92
        if attempt_count >= 4:
            return 90
        if attempt_count >= 3:
            return 85
        return 75

    def _build_failure_evidence(self, attempts: Iterable[SearchAttempt]) -> str:
        parts = []
        for attempt in attempts:
            if attempt.success:
                continue
            err = f" ({attempt.error})" if attempt.error else ""
            parts.append(f"{attempt.source}:{attempt.strategy} failed{err}")

        if not parts:
            return "No verification evidence available."
        return "; ".join(parts)

    def _cache_key(self, value: str) -> str:
        return self._canonical_text(value)

    def _canonical_text(self, value: str) -> str:
        lowered = value.lower().strip()
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _reporter_triplet(self, citation: str) -> Optional[Tuple[str, str, str]]:
        pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")
        match = pattern.search(citation)
        if not match:
            return None

        return (
            match.group(1),
            self._canonical_text(match.group(2)),
            match.group(3),
        )

    def _triplet_match(self, value: str, target: Tuple[str, str, str]) -> bool:
        candidate = self._reporter_triplet(value)
        if candidate is None:
            return False
        return candidate == target

    def _import_python_docx_document(self) -> Any:
        try:
            from docx import Document  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "python-docx is required for DOCX processing. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc
        return Document

    def _import_eyecite_get_citations(self) -> Any:
        try:
            from eyecite import get_citations  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "eyecite is required for citation extraction. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc
        return get_citations

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"[citation-checker] {message}")
