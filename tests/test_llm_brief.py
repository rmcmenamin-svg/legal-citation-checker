"""Test the citation checker against an LLM-generated brief.

Uses a brief containing 10 real SCOTUS citations and 8 fabricated ones
that mimic typical LLM hallucination patterns. The mock CourtListener API
returns results only for real citations, simulating production behavior.
"""

from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from legal_citation_checker.pipeline import CitationChecker

# Real citations that CourtListener would return results for.
# Maps canonical citation -> (case_name, absolute_url)
REAL_CITATIONS = {
    "389 U.S. 347": ("Katz v. United States", "/opinion/107564/katz-v-united-states/"),
    "585 U.S. 296": ("Carpenter v. United States", "/opinion/4604082/carpenter-v-united-states/"),
    "573 U.S. 373": ("Riley v. California", "/opinion/2723065/riley-v-california/"),
    "442 U.S. 735": ("Smith v. Maryland", "/opinion/110082/smith-v-maryland/"),
    "556 U.S. 332": ("Arizona v. Gant", "/opinion/1582/arizona-v-gant/"),
    "437 U.S. 385": ("Mincey v. Arizona", "/opinion/109883/mincey-v-arizona/"),
    "489 U.S. 602": ("Skinner v. Railway Labor Executives' Ass'n", "/opinion/112215/skinner-v-rlba/"),
    "578 U.S. 330": ("Spokeo, Inc. v. Robins", "/opinion/3210690/spokeo-inc-v-robins/"),
    "594 U.S. 413": ("TransUnion LLC v. Ramirez", "/opinion/6168748/transunion-llc-v-ramirez/"),
    "565 U.S. 400": ("United States v. Jones", "/opinion/627786/united-states-v-jones/"),
}

# Fabricated citations that should NOT be found.
FAKE_CITATIONS = {
    "847 F.3d 1203",   # Thompson v. Digital Analytics Corp.
    "612 F. Supp. 3d 894",  # Rodriguez v. DataMine Systems
    "923 F.3d 1108",   # Henderson v. Clearview Analytics
    "198 F. Supp. 3d 1142",  # Martinez v. Palantir Technologies
    "891 F.3d 445",    # Collins v. SafeTrack Inc.
    "756 F.3d 1087",   # Patterson v. United States
    "834 F.3d 921",    # Walker v. NSA Digital Programs
    "743 F. Supp. 3d 201",  # Chen v. FBI
}

TEST_DOCS = Path(__file__).parent / "test_documents"


def _mock_courtlistener(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
    """Mock that returns results only for real citations."""
    params = kwargs.get("params", {})
    query = str(params.get("q", ""))

    # Check if the query contains a real citation's volume and page
    for cite, (name, cl_url) in REAL_CITATIONS.items():
        parts = cite.split()
        volume, page = parts[0], parts[-1]
        if volume in query and page in query:
            return {
                "count": 1,
                "results": [{
                    "citation": [cite],
                    "case_name": name,
                    "absolute_url": cl_url,
                    "court": "scotus",
                    "date_filed": "1967-12-18",
                }],
            }, url, None

    # Not found
    return {"count": 0, "results": []}, url, None


class TestLLMGeneratedBrief:
    """End-to-end test: can the checker distinguish real from hallucinated citations?"""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        try:
            from docx import Document  # type: ignore  # noqa: F401
        except ImportError:
            pytest.skip("python-docx not installed")

        self.doc_path = TEST_DOCS / "llm_generated_brief.docx"
        if not self.doc_path.exists():
            pytest.skip("LLM brief not generated — run generate_llm_brief.py first")

        self.checker = CitationChecker(verbose=False, max_workers=1)
        self.checker._verifier._http_get_json = _mock_courtlistener  # type: ignore[assignment]
        self.checker._verifier._session = None  # Disable Google Scholar / web search

    def test_extracts_all_citations(self) -> None:
        report = self.checker.process_document(self.doc_path)
        # 18 unique case citations (Carpenter appears twice but should dedup)
        # Statute (42 U.S.C. § 1983) should be filtered out
        assert report.total_citations >= 15, (
            f"Expected at least 15 citations, got {report.total_citations}"
        )

    def test_real_citations_verified(self) -> None:
        report = self.checker.process_document(self.doc_path)
        verified = [c for c in report.citations if "Verified" in c.status]
        # Should verify most of the 10 real SCOTUS citations
        assert len(verified) >= 7, (
            f"Expected at least 7 verified citations, got {len(verified)}: "
            f"{[c.raw_citation for c in verified]}"
        )

    def test_fake_citations_flagged(self) -> None:
        report = self.checker.process_document(self.doc_path)
        hallucinated = [c for c in report.citations if "Hallucination" in c.status]
        # Should flag most of the 8 fabricated citations
        assert len(hallucinated) >= 5, (
            f"Expected at least 5 hallucinations, got {len(hallucinated)}: "
            f"{[c.raw_citation for c in hallucinated]}"
        )

    def test_statute_filtered(self) -> None:
        report = self.checker.process_document(self.doc_path)
        for c in report.citations:
            assert "U.S.C." not in c.raw_citation, (
                f"Statute should be filtered: {c.raw_citation}"
            )

    def test_no_false_positives_on_real_cases(self) -> None:
        """Real citations should NEVER be flagged as hallucinations."""
        report = self.checker.process_document(self.doc_path)
        for c in report.citations:
            if "Hallucination" in c.status:
                # Make sure it's not one of our known real citations
                for real_cite in REAL_CITATIONS:
                    parts = real_cite.split()
                    volume, page = parts[0], parts[-1]
                    if volume in c.raw_citation and page in c.raw_citation:
                        pytest.fail(
                            f"Real citation flagged as hallucination: "
                            f"{c.raw_citation} (matched {real_cite})"
                        )

    def test_report_summary_accuracy(self) -> None:
        report = self.checker.process_document(self.doc_path)
        total = report.total_citations
        verified = report.verified_count
        hallucinated = report.hallucination_count
        needs_review = report.needs_review_count

        # Counts should add up
        assert verified + hallucinated + needs_review == total, (
            f"Counts don't add up: {verified} + {hallucinated} + {needs_review} != {total}"
        )

        # Should have both verified and hallucinated
        assert verified > 0, "Expected some verified citations"
        assert hallucinated > 0, "Expected some hallucinated citations"

    def test_detailed_results_table(self) -> None:
        """Print a detailed comparison for manual review."""
        report = self.checker.process_document(self.doc_path)

        print("\n" + "=" * 80)
        print("LLM BRIEF CITATION CHECK RESULTS")
        print("=" * 80)
        print(f"Total: {report.total_citations} | Verified: {report.verified_count} | "
              f"Hallucinated: {report.hallucination_count} | Needs Review: {report.needs_review_count}")
        print("-" * 80)

        for c in report.citations:
            # Determine if this is actually real or fake
            is_real = False
            for real_cite in REAL_CITATIONS:
                parts = real_cite.split()
                if parts[0] in c.raw_citation and parts[-1] in c.raw_citation:
                    is_real = True
                    break

            expected = "REAL" if is_real else "FAKE"
            correct = (
                ("Verified" in c.status and is_real)
                or ("Hallucination" in c.status and not is_real)
            )
            marker = "✓" if correct else "✗"

            print(f"  {marker} [{expected}] {c.raw_citation:30s} → {c.status} ({c.confidence}%)")

        print("=" * 80)
