"""Integration tests using sample test documents."""

from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from legal_citation_checker.pipeline import CitationChecker

TEST_DOCS = Path(__file__).parent / "test_documents"


def _make_checker_with_mock(mock_fn: Any) -> CitationChecker:
    checker = CitationChecker(verbose=False, max_workers=1)
    checker._verifier._http_get_json = mock_fn  # type: ignore[assignment]
    # Also mock the session GET for Google Scholar
    checker._verifier._session = None  # Disable Google Scholar for controlled tests
    return checker


class TestRealBrief:
    def test_extracts_multiple_citations(self) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = TEST_DOCS / "real_brief.docx"
        if not doc_path.exists():
            pytest.skip("Test document not found")

        import re

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            # Extract the citation from the query and echo it back as a match
            params = kwargs.get("params", {})
            query = str(params.get("q", ""))
            # Find anything that looks like a volume/reporter/page
            m = re.search(r"(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]+?)\s+(\d{1,5})", query)
            cite = m.group(0) if m else "347 U.S. 483"
            return {
                "count": 1,
                "results": [{"citation": [cite], "absolute_url": "/opinion/123/"}],
            }, url, None

        checker = _make_checker_with_mock(mock_http)
        report = checker.process_document(doc_path)

        # Should extract at least 4 case citations (Brown, Gideon, Strickland, Mapp, Weeks)
        assert report.total_citations >= 4
        # Statute (42 U.S.C. § 1983) should be filtered out, not counted
        assert report.hallucination_count == 0

    def test_statutes_are_filtered(self) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = TEST_DOCS / "real_brief.docx"
        if not doc_path.exists():
            pytest.skip("Test document not found")

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 1, "results": [{"citation": ["dummy"], "absolute_url": "/x/"}]}, url, None

        checker = _make_checker_with_mock(mock_http)
        report = checker.process_document(doc_path)

        # No citation should contain "U.S.C."
        for c in report.citations:
            assert "U.S.C." not in c.raw_citation


class TestHallucinatedBrief:
    def test_flags_fabricated_citations(self) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = TEST_DOCS / "hallucinated_brief.docx"
        if not doc_path.exists():
            pytest.skip("Test document not found")

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 0, "results": []}, url, None

        checker = _make_checker_with_mock(mock_http)
        report = checker.process_document(doc_path)

        assert report.total_citations >= 2
        # All should be flagged since mock returns no results
        assert report.hallucination_count >= 2
        assert report.verified_count == 0


class TestMixedBrief:
    def test_mixed_document_has_both_statuses(self) -> None:
        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = TEST_DOCS / "mixed_brief.docx"
        if not doc_path.exists():
            pytest.skip("Test document not found")

        # Mock that returns results only for real citations
        real_citations = {"376 u s 254", "384 u s 436"}

        def selective_mock(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            params = kwargs.get("params", {})
            query = str(params.get("q", "")).lower()
            # Check if query contains a real citation's volume/page
            for cite in real_citations:
                parts = cite.split()
                if len(parts) >= 3 and parts[0] in query and parts[-1] in query:
                    return {
                        "count": 1,
                        "results": [{"citation": [cite], "absolute_url": "/opinion/1/"}],
                    }, url, None
            return {"count": 0, "results": []}, url, None

        checker = _make_checker_with_mock(selective_mock)
        report = checker.process_document(doc_path)

        assert report.total_citations >= 3
        # Should have at least some verified and some hallucinations
        statuses = {c.status for c in report.citations}
        assert len(statuses) >= 2  # At least two different statuses


class TestReportFormats:
    def test_all_formats_work_on_real_doc(self, tmp_path: Path) -> None:
        import re as _re

        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        doc_path = TEST_DOCS / "real_brief.docx"
        if not doc_path.exists():
            pytest.skip("Test document not found")

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            params = kwargs.get("params", {})
            query = str(params.get("q", ""))
            m = _re.search(r"(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]+?)\s+(\d{1,5})", query)
            cite = m.group(0) if m else "347 U.S. 483"
            return {
                "count": 1,
                "results": [{"citation": [cite], "absolute_url": "/opinion/123/"}],
            }, url, None

        checker = _make_checker_with_mock(mock_http)
        report = checker.process_document(doc_path)

        for fmt in ("markdown", "html", "json"):
            output = report.to_string(format=fmt)
            assert len(output) > 100, f"Empty output for {fmt}"

            out_path = tmp_path / f"report.{fmt}"
            report.save(out_path, format=fmt)
            assert out_path.exists()
            assert out_path.stat().st_size > 0
