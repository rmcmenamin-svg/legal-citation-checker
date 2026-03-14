"""Tests for the Bluebook citation formatter."""

from legal_citation_checker.formatter import BluebookFormatter
from legal_citation_checker.models import ParsedCitation


class TestBluebookFormatFull:
    def setup_method(self) -> None:
        self.f = BluebookFormatter()

    def test_scotus_in_us_reports(self) -> None:
        """SCOTUS in U.S. Reports omits court from parenthetical."""
        p = ParsedCitation(
            volume="347", reporter="U.S.", page="483",
            plaintiff="Brown", defendant="Board of Education",
            year="1954", court="scotus",
        )
        result = self.f.format(p)
        assert result == "Brown v. Bd. of Educ., 347 U.S. 483 (1954)."

    def test_circuit_court(self) -> None:
        """Circuit courts include court abbreviation in parenthetical."""
        p = ParsedCitation(
            volume="847", reporter="F.3d", page="1203",
            plaintiff="Thompson", defendant="Digital Analytics Corporation",
            year="2021", court="ca9",
        )
        result = self.f.format(p)
        assert "9th Cir." in result
        assert "2021" in result
        assert "Corp." in result

    def test_district_court(self) -> None:
        p = ParsedCitation(
            volume="612", reporter="F. Supp. 3d", page="894",
            plaintiff="Rodriguez", defendant="DataMine Systems",
            year="2023", court="cand",
        )
        result = self.f.format(p)
        assert "Sys." in result
        assert "612 F. Supp. 3d 894" in result

    def test_no_case_name(self) -> None:
        """Citation without party names still formats volume/reporter/page."""
        p = ParsedCitation(volume="347", reporter="U.S.", page="483", year="1954", court="scotus")
        result = self.f.format(p)
        assert result == "347 U.S. 483 (1954)."

    def test_no_year(self) -> None:
        p = ParsedCitation(
            volume="347", reporter="U.S.", page="483",
            plaintiff="Brown", defendant="Board of Education",
            court="scotus",
        )
        result = self.f.format(p)
        assert "347 U.S. 483." == result or "347 U.S. 483" in result

    def test_empty_without_triplet(self) -> None:
        p = ParsedCitation()
        assert self.f.format(p) == ""

    def test_with_pincite(self) -> None:
        p = ParsedCitation(
            volume="347", reporter="U.S.", page="483",
            plaintiff="Brown", defendant="Board of Education",
            year="1954", court="scotus", pincite="495",
        )
        result = self.f.format_full(p, include_pincite=True)
        assert "495" in result
        assert "483, 495" in result


class TestCaseNameAbbreviation:
    def setup_method(self) -> None:
        self.f = BluebookFormatter()

    def test_board_of_education(self) -> None:
        assert self.f.abbreviate_case_name("Brown v. Board of Education") == "Brown v. Bd. of Educ."

    def test_railway_labor(self) -> None:
        result = self.f.abbreviate_case_name("Skinner v. Railway Labor Executives' Association")
        assert "Ry." in result
        assert "Ass'n" in result

    def test_corporation(self) -> None:
        result = self.f.abbreviate_case_name("Thompson v. Digital Analytics Corporation")
        assert "Corp." in result

    def test_department(self) -> None:
        result = self.f.abbreviate_case_name("Doe v. Department of Justice")
        assert "Dep't" in result

    def test_national_international(self) -> None:
        result = self.f.abbreviate_case_name("National Association v. International Corporation")
        assert "Nat'l" in result
        assert "Ass'n" in result
        assert "Int'l" in result
        assert "Corp." in result

    def test_preserves_single_name(self) -> None:
        """Simple names with no abbreviable words stay the same."""
        assert self.f.abbreviate_case_name("Riley v. California") == "Riley v. California"

    def test_empty_string(self) -> None:
        assert self.f.abbreviate_case_name("") == ""

    def test_strips_leading_the(self) -> None:
        result = self.f.abbreviate_case_name("The Board of Education v. Smith")
        assert result.startswith("Bd.")

    def test_inc_preserved(self) -> None:
        """'Inc.' is already abbreviated, should not be double-abbreviated."""
        result = self.f.abbreviate_case_name("Spokeo, Inc. v. Robins")
        assert "Inc." in result


class TestShortForm:
    def setup_method(self) -> None:
        self.f = BluebookFormatter()

    def test_short_form_with_pincite(self) -> None:
        p = ParsedCitation(
            volume="347", reporter="U.S.", page="483",
            plaintiff="Brown", defendant="Board of Education",
            pincite="495",
        )
        result = self.f.format_short(p)
        assert result == "Brown, 347 U.S. at 495."

    def test_short_form_without_pincite(self) -> None:
        p = ParsedCitation(
            volume="347", reporter="U.S.", page="483",
            plaintiff="Brown", defendant="Board of Education",
        )
        result = self.f.format_short(p)
        assert result == "Brown, 347 U.S. 483."

    def test_short_form_no_parties(self) -> None:
        p = ParsedCitation(volume="347", reporter="U.S.", page="483")
        result = self.f.format_short(p)
        assert result == "347 U.S. 483."


class TestCourtCitationString:
    def setup_method(self) -> None:
        self.f = BluebookFormatter()

    def test_scotus_empty(self) -> None:
        """SCOTUS has no court string (omitted in U.S. Reports)."""
        assert self.f.court_citation_string("scotus") == ""

    def test_ninth_circuit(self) -> None:
        assert self.f.court_citation_string("ca9") == "9th Cir."

    def test_dc_circuit(self) -> None:
        assert self.f.court_citation_string("cadc") == "D.C. Cir."

    def test_seventh_circuit(self) -> None:
        assert self.f.court_citation_string("ca7") == "7th Cir."


class TestStateAbbreviation:
    def setup_method(self) -> None:
        self.f = BluebookFormatter()

    def test_california(self) -> None:
        assert self.f.abbreviate_state("California") == "Cal."

    def test_new_york(self) -> None:
        assert self.f.abbreviate_state("New York") == "N.Y."

    def test_unknown_passes_through(self) -> None:
        assert self.f.abbreviate_state("Atlantis") == "Atlantis"


class TestFormatterInPipeline:
    """Verify formatter is integrated into the pipeline output."""

    def test_report_includes_bluebook_citation(self) -> None:
        from pathlib import Path
        from typing import Any, Dict, Tuple

        import pytest

        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        from legal_citation_checker.pipeline import CitationChecker

        doc_path = Path(__file__).parent / "test_documents" / "llm_generated_brief.docx"
        if not doc_path.exists():
            pytest.skip("LLM brief not generated")

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 1, "results": [{"citation": ["347 U.S. 483"], "absolute_url": "/x/"}]}, url, None

        checker = CitationChecker(verbose=False, max_workers=1)
        checker._verifier._http_get_json = mock_http  # type: ignore[assignment]
        checker._verifier._session = None

        report = checker.process_document(doc_path)

        # At least some citations should have Bluebook formatting
        with_bluebook = [c for c in report.citations if c.bluebook_citation]
        assert len(with_bluebook) > 0, "No citations got Bluebook formatting"

        # Check a known one
        for c in report.citations:
            if "389" in c.raw_citation and "347" not in c.raw_citation:
                # Katz v. United States, 389 U.S. 347
                if c.bluebook_citation:
                    assert "389 U.S. 347" in c.bluebook_citation

    def test_markdown_report_shows_bluebook(self) -> None:
        from legal_citation_checker.models import CitationAudit
        from legal_citation_checker.report import AuditReport

        report = AuditReport(
            source_document="test.docx",
            generated_at="2024-01-01",
            processing_seconds=1.0,
            citations=[
                CitationAudit(
                    index=1,
                    raw_citation="347 U.S. 483",
                    normalized_citation="347 U.S. 483",
                    citation_type="FullCaseCitation",
                    context="...",
                    paragraph_index=1,
                    metadata={},
                    bluebook_normalized=False,
                    status="Verified (CourtListener)",
                    confidence=95,
                    source="CourtListener",
                    source_url=None,
                    evidence="...",
                    bluebook_citation="Brown v. Bd. of Educ., 347 U.S. 483 (1954).",
                ),
            ],
        )
        md = report.to_string(format="markdown")
        assert "Bluebook format" in md
        assert "Brown v. Bd. of Educ." in md
