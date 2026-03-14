"""Tests for the refactored modules (models, normalizer, verifier, extractors)."""

from typing import Any, Dict, Optional, Tuple

import pytest

from legal_citation_checker.models import (
    ExtractedCitation,
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
        from legal_citation_checker.pipeline import CitationChecker

        checker = CitationChecker(verbose=False, max_workers=1, disable_cache=True)
        # Pre-populate the cache
        from legal_citation_checker.normalizer import canonical_text
        key = canonical_text("347 U.S. 483")
        checker._verification_cache[key] = VerificationDecision(
            status="Verified (Cached)", confidence=95
        )

        # With disable_cache=True, the cache should be skipped
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
        # Should NOT return the cached "Verified (Cached)" result
        assert decision.status != "Verified (Cached)"
