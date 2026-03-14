"""Tests for the citation checker pipeline."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from legal_citation_checker.pipeline import (
    AuditReport,
    CitationAudit,
    CitationChecker,
    ExtractedCitation,
    SearchAttempt,
    VerificationDecision,
    _SKIP_CITATION_TYPES,
    _WESTLAW_PATTERN,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def make_citation(
    index: int = 1,
    raw: str = "347 U.S. 483",
    normalized: str = "347 U.S. 483",
    citation_type: str = "FullCaseCitation",
    metadata: Optional[Dict[str, Any]] = None,
) -> ExtractedCitation:
    return ExtractedCitation(
        index=index,
        raw_citation=raw,
        normalized_citation=normalized,
        citation_type=citation_type,
        context=f"...see {raw}...",
        paragraph_index=1,
        metadata=metadata or {"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
        bluebook_normalized=False,
    )


def make_checker(**kwargs: Any) -> CitationChecker:
    return CitationChecker(verbose=False, max_workers=1, **kwargs)


# ---------------------------------------------------------------------------
# Unit tests: Bluebook normalization
# ---------------------------------------------------------------------------

class TestNormalizeBluebook:
    def test_normalizes_whitespace(self) -> None:
        checker = make_checker()
        result, changed = checker._normalize_bluebook("347  U.S.   483", {})
        assert "  " not in result

    def test_normalizes_section_symbol(self) -> None:
        checker = make_checker()
        result, _ = checker._normalize_bluebook("Section 1983", {})
        assert "§ 1983" in result

    def test_normalizes_v_separator(self) -> None:
        checker = make_checker()
        result, _ = checker._normalize_bluebook("Brown v Board", {})
        assert "v." in result

    def test_strips_trailing_semicolons(self) -> None:
        checker = make_checker()
        result, _ = checker._normalize_bluebook("347 U.S. 483;", {})
        assert not result.endswith(";")

    def test_preserves_already_correct_citation(self) -> None:
        checker = make_checker()
        result, changed = checker._normalize_bluebook("347 U.S. 483", {})
        assert result == "347 U.S. 483"
        assert not changed


# ---------------------------------------------------------------------------
# Unit tests: Statute/regulation detection
# ---------------------------------------------------------------------------

class TestStatuteDetection:
    def test_usc_detected(self) -> None:
        assert CitationChecker._is_statute_or_regulation("42 U.S.C. § 1983")

    def test_cfr_detected(self) -> None:
        assert CitationChecker._is_statute_or_regulation("29 C.F.R. Part 1926")

    def test_pub_law_detected(self) -> None:
        assert CitationChecker._is_statute_or_regulation("Pub. L. No. 111-148")

    def test_state_statute_detected(self) -> None:
        assert CitationChecker._is_statute_or_regulation("Cal. Code § 452")

    def test_case_citation_not_detected(self) -> None:
        assert not CitationChecker._is_statute_or_regulation("347 U.S. 483")

    def test_case_name_not_detected(self) -> None:
        assert not CitationChecker._is_statute_or_regulation("Brown v. Board of Education")


# ---------------------------------------------------------------------------
# Unit tests: Pincite stripping
# ---------------------------------------------------------------------------

class TestPinciteStripping:
    def test_strips_pincite(self) -> None:
        assert CitationChecker._strip_pincite("347 U.S. 483, 495") == "347 U.S. 483"

    def test_strips_pincite_range(self) -> None:
        assert CitationChecker._strip_pincite("347 U.S. 483, 495-497") == "347 U.S. 483"

    def test_no_pincite_unchanged(self) -> None:
        assert CitationChecker._strip_pincite("347 U.S. 483") == "347 U.S. 483"


# ---------------------------------------------------------------------------
# Unit tests: Westlaw detection
# ---------------------------------------------------------------------------

class TestWestlawDetection:
    def test_wl_citation_detected(self) -> None:
        assert _WESTLAW_PATTERN.match("2025 WL 2192378")

    def test_case_citation_not_detected(self) -> None:
        assert not _WESTLAW_PATTERN.match("347 U.S. 483")


# ---------------------------------------------------------------------------
# Unit tests: Citation type filtering
# ---------------------------------------------------------------------------

class TestCitationTypeFiltering:
    def test_skip_types_defined(self) -> None:
        for t in ("IdCitation", "SupraCitation", "ShortCaseCitation", "NonopinionCitation", "UnknownCitation"):
            assert t in _SKIP_CITATION_TYPES

    def test_full_case_not_skipped(self) -> None:
        assert "FullCaseCitation" not in _SKIP_CITATION_TYPES


# ---------------------------------------------------------------------------
# Unit tests: Cache key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_canonical_text_lowered(self) -> None:
        checker = make_checker()
        assert checker._canonical_text("Brown V. BOARD") == "brown v board"

    def test_canonical_text_strips_punctuation(self) -> None:
        checker = make_checker()
        assert checker._canonical_text("347 U.S. 483") == "347 u s 483"

    def test_cache_key_deduplicates(self) -> None:
        checker = make_checker()
        assert checker._cache_key("347 U.S. 483") == checker._cache_key("347 U.S.  483")


# ---------------------------------------------------------------------------
# Unit tests: Reporter triplet
# ---------------------------------------------------------------------------

class TestReporterTriplet:
    def test_extracts_triplet(self) -> None:
        checker = make_checker()
        result = checker._reporter_triplet("347 U.S. 483")
        assert result is not None
        vol, reporter, page = result
        assert vol == "347"
        assert page == "483"

    def test_no_triplet_in_text(self) -> None:
        checker = make_checker()
        assert checker._reporter_triplet("some random text") is None

    def test_triplet_match_works(self) -> None:
        checker = make_checker()
        target = checker._reporter_triplet("347 U.S. 483")
        assert target is not None
        assert checker._triplet_match("347 U.S. 483", target)
        assert not checker._triplet_match("348 U.S. 483", target)


# ---------------------------------------------------------------------------
# Unit tests: Raw reporter extraction
# ---------------------------------------------------------------------------

class TestRawReporter:
    def test_extracts_reporter(self) -> None:
        assert CitationChecker._raw_reporter_from_citation("56 Cal. 2d 407") == "Cal. 2d"

    def test_extracts_reporter_with_app(self) -> None:
        assert CitationChecker._raw_reporter_from_citation("101 Cal. App. 5th 902") == "Cal. App. 5th"


# ---------------------------------------------------------------------------
# Unit tests: Needs Review vs Hallucination
# ---------------------------------------------------------------------------

class TestVerificationDecisions:
    def test_all_network_errors_yields_needs_review(self) -> None:
        checker = make_checker()
        citation = make_citation()

        def error_http_get(*args: Any, **kwargs: Any) -> Tuple[None, None, str]:
            return None, None, "Connection timeout"

        checker._http_get_json = error_http_get  # type: ignore[assignment]

        decision = checker._verify_citation(citation)
        assert decision.status == "Needs Review"
        assert decision.confidence == 0

    def test_real_not_found_yields_hallucination(self) -> None:
        checker = make_checker()
        citation = make_citation()

        def empty_http_get(*args: Any, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 0, "results": []}, "http://example.com", None

        checker._http_get_json = empty_http_get  # type: ignore[assignment]

        decision = checker._verify_citation(citation)
        assert decision.status == "Potential Hallucination"
        assert decision.confidence > 0

    def test_verified_on_courtlistener_match(self) -> None:
        checker = make_checker()
        citation = make_citation()

        def mock_http_get(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{"citation": ["347 U.S. 483"], "absolute_url": "/opinion/123/"}],
            }, url, None

        checker._http_get_json = mock_http_get  # type: ignore[assignment]
        decision = checker._verify_citation(citation)
        assert decision.status.startswith("Verified")
        assert decision.confidence >= 85

    def test_westlaw_citation_needs_review(self) -> None:
        checker = make_checker()
        citation = make_citation(raw="2025 WL 2192378", normalized="2025 WL 2192378")
        decision = checker._verify_citation(citation)
        assert decision.status == "Needs Review"
        assert "Westlaw" in decision.evidence


# ---------------------------------------------------------------------------
# Unit tests: Audit report
# ---------------------------------------------------------------------------

class TestAuditReport:
    def _make_report(self, statuses: List[str]) -> AuditReport:
        citations = []
        for i, status in enumerate(statuses, 1):
            citations.append(
                CitationAudit(
                    index=i,
                    raw_citation=f"cite {i}",
                    normalized_citation=f"cite {i}",
                    citation_type="FullCaseCitation",
                    context="...",
                    paragraph_index=1,
                    metadata={},
                    bluebook_normalized=False,
                    status=status,
                    confidence=90,
                    source=None,
                    source_url=None,
                    evidence="",
                )
            )
        return AuditReport(
            source_document="test.docx",
            generated_at="2026-01-01T00:00:00+00:00",
            processing_seconds=1.0,
            citations=citations,
        )

    def test_counts(self) -> None:
        report = self._make_report([
            "Verified (CourtListener)",
            "Potential Hallucination",
            "Needs Review",
            "Skipped (Non-Case Citation)",
        ])
        assert report.total_citations == 4
        assert report.verified_count == 1
        assert report.hallucination_count == 1
        assert report.needs_review_count == 1
        assert report.skipped_count == 1

    def test_json_output(self) -> None:
        report = self._make_report(["Verified (CourtListener)"])
        output = report.to_string(format="json")
        data = json.loads(output)
        assert data["summary"]["verified"] == 1
        assert data["summary"]["needs_review"] == 0

    def test_markdown_output(self) -> None:
        report = self._make_report(["Needs Review"])
        output = report.to_string(format="markdown")
        assert "needs review" in output.lower()

    def test_html_output(self) -> None:
        report = self._make_report(["Verified (CourtListener)"])
        output = report.to_string(format="html")
        assert "<html" in output
        assert "Verified" in output


# ---------------------------------------------------------------------------
# Unit tests: Broad query building
# ---------------------------------------------------------------------------

class TestQueryBuilding:
    def test_broad_query_includes_parts(self) -> None:
        checker = make_checker()
        citation = make_citation()
        query = checker._build_broad_query(citation)
        assert "Brown" in query
        assert "347 U.S. 483" in query

    def test_case_name_from_metadata(self) -> None:
        checker = make_checker()
        name = checker._case_name_from_metadata({"plaintiff": "Brown", "defendant": "Board of Education"})
        assert name == "Brown v. Board of Education"

    def test_case_name_fallback(self) -> None:
        checker = make_checker()
        name = checker._case_name_from_metadata({"case_name": "Some Case"})
        assert name == "Some Case"


# ---------------------------------------------------------------------------
# Integration-level: process_document smoke test (mocked DOCX)
# ---------------------------------------------------------------------------

class TestProcessDocumentSmoke:
    def test_empty_document(self, tmp_path: Path) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = tmp_path / "empty.docx"
        doc = Document()
        doc.add_paragraph("This document has no legal citations.")
        doc.save(str(doc_path))

        checker = make_checker()
        report = checker.process_document(doc_path)
        assert report.total_citations == 0

    def test_document_with_case_citation(self, tmp_path: Path) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = tmp_path / "brief.docx"
        doc = Document()
        doc.add_paragraph(
            "The Court held in Brown v. Board of Education, 347 U.S. 483 (1954), "
            "that segregation violates the Equal Protection Clause."
        )
        doc.save(str(doc_path))

        checker = make_checker()

        def mock_http_get(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{"citation": ["347 U.S. 483"], "absolute_url": "/opinion/123/"}],
            }, url, None

        checker._http_get_json = mock_http_get  # type: ignore[assignment]
        report = checker.process_document(doc_path)
        assert report.total_citations >= 1
        assert report.verified_count >= 1

    def test_document_with_statute(self, tmp_path: Path) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = tmp_path / "statute.docx"
        doc = Document()
        doc.add_paragraph("Pursuant to 42 U.S.C. § 1983, the plaintiff seeks relief.")
        doc.save(str(doc_path))

        checker = make_checker()
        report = checker.process_document(doc_path)
        assert report.hallucination_count == 0

    def test_pdf_document(self, tmp_path: Path) -> None:
        """Process a PDF with a citation (mocked verification)."""
        try:
            import pdfplumber  # type: ignore
            from reportlab.lib.pagesizes import letter  # type: ignore
            from reportlab.pdfgen import canvas  # type: ignore
        except ImportError:
            pytest.skip("pdfplumber or reportlab not installed")

        pdf_path = tmp_path / "brief.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(72, 700, "The Court held in Brown v. Board of Education, 347 U.S. 483 (1954).")
        c.save()

        checker = make_checker()

        def mock_http_get(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{"citation": ["347 U.S. 483"], "absolute_url": "/opinion/123/"}],
            }, url, None

        checker._http_get_json = mock_http_get  # type: ignore[assignment]
        report = checker.process_document(pdf_path)
        assert report.total_citations >= 1

    def test_executive_summary_in_markdown(self) -> None:
        """Markdown report should contain Action Required section when hallucinations exist."""
        from legal_citation_checker.pipeline import AuditReport, CitationAudit

        report = AuditReport(
            source_document="test.docx",
            generated_at="2026-01-01T00:00:00+00:00",
            processing_seconds=1.0,
            citations=[
                CitationAudit(
                    index=1,
                    raw_citation="999 F.3d 999",
                    normalized_citation="999 F.3d 999",
                    citation_type="FullCaseCitation",
                    context="See Fake v. Case, 999 F.3d 999 (9th Cir. 2099).",
                    paragraph_index=1,
                    metadata={},
                    bluebook_normalized=False,
                    status="Potential Hallucination",
                    confidence=92,
                    source=None,
                    source_url=None,
                    evidence="Not found",
                ),
            ],
        )
        md = report.to_string(format="markdown")
        assert "Action Required" in md
        assert "999 F.3d 999" in md

    def test_document_with_westlaw_citation(self, tmp_path: Path) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = tmp_path / "westlaw.docx"
        doc = Document()
        doc.add_paragraph(
            "See Smith v. Jones, 2025 WL 2192378 (Cal. Ct. App. 2025)."
        )
        doc.save(str(doc_path))

        checker = make_checker()
        report = checker.process_document(doc_path)
        # WL citations should be "Needs Review", not hallucination.
        assert report.hallucination_count == 0
