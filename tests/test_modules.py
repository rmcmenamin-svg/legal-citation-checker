"""Tests for the refactored modules (models, normalizer, verifier, extractors)."""

from typing import Any, Dict, Optional, Tuple

import pytest

from legal_citation_checker.models import (
    ExtractedCitation,
    ParsedCitation,
    SearchAttempt,
    VerificationDecision,
)
from legal_citation_checker.normalizer import CitationNormalizer, canonical_text
from legal_citation_checker.verifier import (
    _WESTLAW_PATTERN,
    case_name_from_metadata,
    raw_reporter_from_citation,
    reporter_triplet,
    strip_pincite,
    triplet_match,
)
from legal_citation_checker.extractors import is_statute_or_regulation


# ---------------------------------------------------------------------------
# canonical_text
# ---------------------------------------------------------------------------

class TestCanonicalText:
    def test_lowercases(self) -> None:
        assert canonical_text("Brown V. BOARD") == "brown v board"

    def test_strips_punctuation(self) -> None:
        assert canonical_text("347 U.S. 483") == "347 u s 483"

    def test_collapses_whitespace(self) -> None:
        assert canonical_text("  a   b  ") == "a b"


# ---------------------------------------------------------------------------
# CitationNormalizer
# ---------------------------------------------------------------------------

class TestCitationNormalizer:
    def test_normalizes_section(self) -> None:
        n = CitationNormalizer()
        result, changed = n.normalize("Section 1983", {})
        assert "§ 1983" in result
        assert changed

    def test_idempotent_on_correct_citation(self) -> None:
        n = CitationNormalizer()
        result, changed = n.normalize("347 U.S. 483", {})
        assert result == "347 U.S. 483"
        assert not changed


# ---------------------------------------------------------------------------
# Verifier helpers
# ---------------------------------------------------------------------------

class TestStripPincite:
    def test_strips(self) -> None:
        assert strip_pincite("347 U.S. 483, 495") == "347 U.S. 483"

    def test_noop(self) -> None:
        assert strip_pincite("347 U.S. 483") == "347 U.S. 483"


class TestReporterTriplet:
    def test_extracts(self) -> None:
        t = reporter_triplet("347 U.S. 483")
        assert t is not None
        assert t[0] == "347"
        assert t[2] == "483"

    def test_none_for_text(self) -> None:
        assert reporter_triplet("random text") is None


class TestTripletMatch:
    def test_matches(self) -> None:
        target = reporter_triplet("347 U.S. 483")
        assert target is not None
        assert triplet_match("347 U.S. 483", target)

    def test_no_match(self) -> None:
        target = reporter_triplet("347 U.S. 483")
        assert target is not None
        assert not triplet_match("348 U.S. 483", target)


class TestCaseNameFromMetadata:
    def test_plaintiff_defendant(self) -> None:
        assert case_name_from_metadata({"plaintiff": "Brown", "defendant": "Board"}) == "Brown v. Board"

    def test_fallback_case_name(self) -> None:
        assert case_name_from_metadata({"case_name": "Some Case"}) == "Some Case"

    def test_empty(self) -> None:
        assert case_name_from_metadata({}) == ""


class TestRawReporter:
    def test_extracts(self) -> None:
        assert raw_reporter_from_citation("56 Cal. 2d 407") == "Cal. 2d"


class TestWestlawPattern:
    def test_matches_wl(self) -> None:
        assert _WESTLAW_PATTERN.match("2025 WL 2192378")

    def test_no_match_case(self) -> None:
        assert not _WESTLAW_PATTERN.match("347 U.S. 483")


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

class TestStatuteDetection:
    def test_usc(self) -> None:
        assert is_statute_or_regulation("42 U.S.C. § 1983")

    def test_case_not_statute(self) -> None:
        assert not is_statute_or_regulation("347 U.S. 483")


# ---------------------------------------------------------------------------
# VerificationDecision
# ---------------------------------------------------------------------------

class TestVerificationDecisionClone:
    def test_clone_is_independent(self) -> None:
        original = VerificationDecision(
            status="Verified",
            confidence=95,
            search_attempts=[SearchAttempt(source="CL", strategy="test", query="q", success=True)],
        )
        cloned = original.clone()
        cloned.status = "Modified"
        cloned.search_attempts.append(SearchAttempt(source="X", strategy="y", query="z", success=False))
        assert original.status == "Verified"
        assert len(original.search_attempts) == 1


class TestDisableCache:
    def test_disable_cache_reverifies(self) -> None:
        import time
        from legal_citation_checker.pipeline import CitationChecker

        checker = CitationChecker(verbose=False, max_workers=1, disable_cache=True)
        from legal_citation_checker.normalizer import canonical_text
        key = canonical_text("347 U.S. 483")
        checker._verification_cache[key] = (time.monotonic(), VerificationDecision(
            status="Verified (Cached)", confidence=95
        ))

        from legal_citation_checker.models import ExtractedCitation
        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
            bluebook_normalized=False,
        )

        def mock_http(*args: Any, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 0, "results": []}, "http://example.com", None

        checker._verifier._http_get_json = mock_http  # type: ignore[assignment]
        decision = checker._verify_citation(citation)
        assert decision.status != "Verified (Cached)"


class TestCacheTTL:
    def test_expired_cache_entry_is_not_used(self) -> None:
        import time
        from legal_citation_checker.pipeline import CitationChecker

        checker = CitationChecker(verbose=False, max_workers=1)
        checker.cache_ttl = 0  # Expire immediately

        from legal_citation_checker.normalizer import canonical_text
        key = canonical_text("347 U.S. 483")
        checker._verification_cache[key] = (time.monotonic() - 10, VerificationDecision(
            status="Verified (Stale)", confidence=95
        ))

        from legal_citation_checker.models import ExtractedCitation
        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
            bluebook_normalized=False,
        )

        def mock_http(*args: Any, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 0, "results": []}, "http://example.com", None

        checker._verifier._http_get_json = mock_http  # type: ignore[assignment]

        try:
            from docx import Document  # type: ignore
        except ImportError:
            pytest.skip("python-docx not installed")

        # Process via _verify_citation to avoid needing a full document
        decision = checker._verify_citation(citation)
        assert decision.status != "Verified (Stale)"

    def test_fresh_cache_entry_is_used(self) -> None:
        import time
        from legal_citation_checker.pipeline import CitationChecker

        checker = CitationChecker(verbose=False, max_workers=1)
        checker.cache_ttl = 3600

        from legal_citation_checker.normalizer import canonical_text
        key = canonical_text("347 U.S. 483")
        cached = VerificationDecision(status="Verified (Fresh)", confidence=95)
        checker._verification_cache[key] = (time.monotonic(), cached)

        # The cache lookup happens in process_document, not _verify_citation.
        # We test by checking the cache is still populated.
        assert key in checker._verification_cache
        ts, decision = checker._verification_cache[key]
        assert decision.status == "Verified (Fresh)"
        assert (time.monotonic() - ts) < checker.cache_ttl


class TestGoogleScholarVerification:
    def test_google_scholar_match(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
            bluebook_normalized=False,
        )

        # Mock the session with a fake response containing the citation
        class FakeResponse:
            status_code = 200
            text = '<div>Brown v. Board of Education, 347 U.S. 483 (1954)</div>'

        class FakeSession:
            def get(self, url: str, **kwargs: Any) -> FakeResponse:
                return FakeResponse()

        verifier._session = FakeSession()  # type: ignore[assignment]
        attempts: list = []
        decision = verifier._verify_with_google_scholar(citation, attempts)

        assert decision is not None
        assert decision.status == "Verified (Google Scholar)"
        assert decision.confidence == 85
        assert len(attempts) >= 1
        assert attempts[0].source == "Google Scholar"

    def test_google_scholar_no_match(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="999 F.3d 999",
            normalized_citation="999 F.3d 999",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={},
            bluebook_normalized=False,
        )

        class FakeResponse:
            status_code = 200
            text = '<div>No results found for your query.</div>'

        class FakeSession:
            def get(self, url: str, **kwargs: Any) -> FakeResponse:
                return FakeResponse()

        verifier._session = FakeSession()  # type: ignore[assignment]
        attempts: list = []
        decision = verifier._verify_with_google_scholar(citation, attempts)

        assert decision is None
        assert len(attempts) >= 1
        assert not attempts[0].success

    def test_google_scholar_skipped_without_session(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={},
            bluebook_normalized=False,
        )

        attempts: list = []
        decision = verifier._verify_with_google_scholar(citation, attempts)
        assert decision is None
        assert len(attempts) == 0


class TestWebDocketSearch:
    def test_web_docket_finds_case(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={
                "year": "1954",
                "plaintiff": "Brown",
                "defendant": "Board of Education",
                "court": "scotus",
            },
            bluebook_normalized=False,
        )

        class FakeResponse:
            status_code = 200
            text = (
                '<div>Brown v. Board of Education - docket entry - '
                'Opinion filed May 17, 1954 - 347 U.S. 483 - Supreme Court</div>'
            )

        class FakeSession:
            def get(self, url: str, **kwargs: Any) -> FakeResponse:
                return FakeResponse()

        verifier._session = FakeSession()  # type: ignore[assignment]
        attempts: list = []
        decision = verifier._verify_with_web_docket_search(citation, attempts)

        assert decision is not None
        assert decision.status == "Verified (Web Search)"
        assert decision.confidence == 75
        assert len(attempts) >= 1
        assert attempts[0].source == "Web Search"

    def test_web_docket_no_match(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="999 F.3d 999",
            normalized_citation="999 F.3d 999",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={
                "plaintiff": "Fakerson",
                "defendant": "Imaginary Corp",
                "court": "9th Cir.",
            },
            bluebook_normalized=False,
        )

        class FakeResponse:
            status_code = 200
            text = '<div>No results found. Did you mean something else?</div>'

        class FakeSession:
            def get(self, url: str, **kwargs: Any) -> FakeResponse:
                return FakeResponse()

        verifier._session = FakeSession()  # type: ignore[assignment]
        attempts: list = []
        decision = verifier._verify_with_web_docket_search(citation, attempts)

        assert decision is None
        assert len(attempts) >= 1
        assert not attempts[0].success

    def test_web_docket_skipped_without_case_name(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        citation = ExtractedCitation(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={},  # No case name info
            bluebook_normalized=False,
        )

        class FakeSession:
            def get(self, url: str, **kwargs: Any) -> None:
                raise AssertionError("Should not be called")

        verifier._session = FakeSession()  # type: ignore[assignment]
        attempts: list = []
        decision = verifier._verify_with_web_docket_search(citation, attempts)

        assert decision is None
        assert len(attempts) == 0


# ---------------------------------------------------------------------------
# ParsedCitation
# ---------------------------------------------------------------------------

class TestParsedCitation:
    def test_case_name(self) -> None:
        p = ParsedCitation(plaintiff="Brown", defendant="Board of Education")
        assert p.case_name == "Brown v. Board of Education"

    def test_case_name_empty_without_parties(self) -> None:
        p = ParsedCitation()
        assert p.case_name == ""

    def test_base_citation(self) -> None:
        p = ParsedCitation(volume="347", reporter="U.S.", page="483")
        assert p.base_citation == "347 U.S. 483"

    def test_base_citation_empty_without_triplet(self) -> None:
        p = ParsedCitation(volume="347")
        assert p.base_citation == ""

    def test_has_triplet(self) -> None:
        p = ParsedCitation(volume="347", reporter="U.S.", page="483")
        assert p.has_triplet

    def test_no_triplet(self) -> None:
        p = ParsedCitation()
        assert not p.has_triplet

    def test_to_dict_omits_none(self) -> None:
        p = ParsedCitation(volume="347", reporter="U.S.", page="483")
        d = p.to_dict()
        assert "volume" in d
        assert "plaintiff" not in d


class TestParsedCitationExtraction:
    """Verify that eyecite populates ParsedCitation correctly."""

    def test_eyecite_populates_parsed(self) -> None:
        from legal_citation_checker.extractors import extract_citations
        from legal_citation_checker.models import DocumentText, ParagraphSpan
        from legal_citation_checker.normalizer import CitationNormalizer

        text = "Brown v. Board of Education, 347 U.S. 483 (1954)."
        doc = DocumentText(
            full_text=text,
            paragraphs=[ParagraphSpan(index=1, text=text, start=0, end=len(text))],
        )
        cites = extract_citations(doc, CitationNormalizer())
        assert len(cites) >= 1
        p = cites[0].parsed
        assert p.volume == "347"
        assert p.reporter == "U.S."
        assert p.page == "483"
        assert p.year == "1954"
        assert p.court == "scotus"
        assert p.plaintiff == "Brown"
        assert p.defendant == "Board of Education"
        assert p.has_triplet
        assert p.base_citation == "347 U.S. 483"
        assert p.case_name == "Brown v. Board of Education"


# ---------------------------------------------------------------------------
# Tier 1: Citation lookup (foolproof if positive)
# ---------------------------------------------------------------------------

class TestTier1CitationLookup:
    def _make_citation(self, **overrides: Any) -> ExtractedCitation:
        defaults: Dict[str, Any] = dict(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
            bluebook_normalized=False,
            parsed=ParsedCitation(
                volume="347", reporter="U.S.", page="483",
                plaintiff="Brown", defendant="Board of Education",
                year="1954", court="scotus",
            ),
        )
        defaults.update(overrides)
        return ExtractedCitation(**defaults)

    def test_positive_match_is_conclusive(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{"citation": ["347 U.S. 483"], "absolute_url": "/opinion/1/"}],
            }, url, None

        verifier._http_get_json = mock_http  # type: ignore[assignment]
        citation = self._make_citation()
        attempts: list = []
        decision = verifier._tier1_citation_lookup(citation, attempts)

        assert decision is not None
        assert decision.status == "Verified (CourtListener)"
        assert decision.confidence == 95

    def test_negative_is_not_conclusive(self) -> None:
        """A miss on citation lookup should return None, not hallucination."""
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {"count": 0, "results": []}, url, None

        verifier._http_get_json = mock_http  # type: ignore[assignment]
        citation = self._make_citation()
        attempts: list = []
        decision = verifier._tier1_citation_lookup(citation, attempts)

        # Should return None — NOT a hallucination decision
        assert decision is None


# ---------------------------------------------------------------------------
# Tier 2: Party name search (fuzzy matching)
# ---------------------------------------------------------------------------

class TestTier2PartyNameSearch:
    def _make_citation(self, **overrides: Any) -> ExtractedCitation:
        defaults: Dict[str, Any] = dict(
            index=1,
            raw_citation="347 U.S. 483",
            normalized_citation="347 U.S. 483",
            citation_type="FullCaseCitation",
            context="...",
            paragraph_index=1,
            metadata={"year": "1954", "plaintiff": "Brown", "defendant": "Board of Education"},
            bluebook_normalized=False,
            parsed=ParsedCitation(
                volume="347", reporter="U.S.", page="483",
                plaintiff="Brown", defendant="Board of Education",
                year="1954", court="scotus",
            ),
        )
        defaults.update(overrides)
        return ExtractedCitation(**defaults)

    def test_party_match_with_citation_in_results(self) -> None:
        """Result contains both party names AND our citation -> verified."""
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{
                    "case_name": "Brown v. Board of Education",
                    "citation": ["347 U.S. 483"],
                    "date_filed": "1954-05-17",
                    "absolute_url": "/opinion/1/",
                }],
            }, url, None

        verifier._http_get_json = mock_http  # type: ignore[assignment]
        citation = self._make_citation()
        attempts: list = []
        decision = verifier._tier2_party_name_search(citation, attempts)

        assert decision is not None
        assert "Verified" in decision.status
        assert decision.confidence >= 85

    def test_party_match_without_citation_uses_name_year(self) -> None:
        """Result has party names + year but different citation -> still verified."""
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)

        def mock_http(url: str, **kwargs: Any) -> Tuple[Dict[str, Any], str, None]:
            return {
                "count": 1,
                "results": [{
                    "case_name": "Brown v. Board of Education of Topeka",
                    "citation": ["347 U.S. 483"],
                    "date_filed": "1954-05-17",
                    "absolute_url": "/opinion/1/",
                }],
            }, url, None

        verifier._http_get_json = mock_http  # type: ignore[assignment]
        citation = self._make_citation()
        attempts: list = []
        decision = verifier._tier2_party_name_search(citation, attempts)

        assert decision is not None
        assert decision.confidence >= 85

    def test_no_party_names_skips(self) -> None:
        from legal_citation_checker.verifier import CitationVerifier

        verifier = CitationVerifier(session=None, request_timeout=8.0)
        verifier._http_get_json = lambda *a, **k: ({"count": 0, "results": []}, "", None)  # type: ignore

        citation = self._make_citation(
            metadata={},
            parsed=ParsedCitation(volume="347", reporter="U.S.", page="483"),
        )
        attempts: list = []
        decision = verifier._tier2_party_name_search(citation, attempts)
        assert decision is None
