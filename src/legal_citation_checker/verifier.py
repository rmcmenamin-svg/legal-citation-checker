"""Citation verification against CourtListener and Google Scholar."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

from .models import ExtractedCitation, SearchAttempt, VerificationDecision
from .normalizer import canonical_text

logger = logging.getLogger("legal_citation_checker")

# Regex to strip pincites: "347 U.S. 483, 495" -> "347 U.S. 483"
_PINCITE_PATTERN = re.compile(r"^(.+?\d+)\s*,\s*\d+(?:\s*[-–]\s*\d+)?$")

# Regex to detect Westlaw citations: "2025 WL 2192378"
_WESTLAW_PATTERN = re.compile(r"^\d{4}\s+WL\s+\d+$", re.IGNORECASE)

# CourtListener search API (the /opinions/ endpoint requires auth, /search/ does not).
COURTLISTENER_SEARCH_BASE = "https://www.courtlistener.com/api/rest/v4/search/"


class CitationVerifier:
    """Verifies citations against CourtListener and secondary sources."""

    def __init__(self, session: Any, request_timeout: float = 8.0) -> None:
        self._session = session
        self.request_timeout = request_timeout

    def verify(self, citation: ExtractedCitation) -> VerificationDecision:
        """Run the full tiered verification pipeline for a citation."""
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

        # Step 3: Additional CourtListener fallback(s)
        decision = self._verify_with_secondary_sources(citation, attempts)
        if decision is not None:
            return decision

        # Step 4: Google Scholar fallback (independent second source)
        decision = self._verify_with_google_scholar(citation, attempts)
        if decision is not None:
            return decision

        # Step 5: Web docket search — distinctive caption word + court name
        decision = self._verify_with_web_docket_search(citation, attempts)
        if decision is not None:
            return decision

        # Step 6: Check if failures were due to network/API issues vs. real "not found".
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

        # Step 7: Hallucination declaration.
        confidence = _hallucination_confidence(len(attempts))
        evidence = _build_failure_evidence(attempts)
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
        base_citation = strip_pincite(citation.normalized_citation)

        strategies = [
            ("citation_search", {"q": f'citation:"{base_citation}"', "type": "o"}),
            ("citation_no_periods", {"q": f'citation:"{base_citation.replace(".", "")}"', "type": "o"}),
            ("broad_search", {"q": _build_broad_query(citation), "type": "o"}),
        ]

        for strategy, params in strategies:
            query = params.get("q", "")
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            match_url = None
            result_count = 0
            success = False
            details = None

            if data is not None:
                result_count = _count_results(data)
                matched_result = _match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = _extract_result_url(matched_result, base="https://www.courtlistener.com")
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

    def _verify_with_courtlistener_citation_lookup(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Second-tier: try CourtListener alternate queries."""
        base_citation = strip_pincite(citation.normalized_citation)
        case_name = case_name_from_metadata(citation.metadata)

        strategies = [
            ("cl_citation_exact", {"q": f'"{base_citation}"', "type": "o"}),
            ("cl_name_citation", {"q": f'{case_name} "{base_citation}"', "type": "o"} if case_name else None),
            ("cl_reporter_triplet", _build_triplet_query(citation)),
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
                result_count = _count_results(data)
                matched_result = _match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = _extract_result_url(matched_result, base="https://www.courtlistener.com")
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

    def _verify_with_secondary_sources(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Third tier: CourtListener relaxed matching."""
        base_citation = strip_pincite(citation.normalized_citation)
        case_name = case_name_from_metadata(citation.metadata)
        meta_year = str(citation.metadata.get("year") or "")

        # Strategy 1: search by volume/reporter/page with year filter.
        triplet = reporter_triplet(base_citation)
        if triplet:
            volume, _reporter_canon, page = triplet
            raw_reporter = raw_reporter_from_citation(base_citation)
            query_str = f'"{volume} {raw_reporter} {page}"'
            if meta_year:
                query_str += f" filed_after:{int(meta_year) - 1}-01-01 filed_before:{int(meta_year) + 1}-12-31"
            params = {"q": query_str, "type": "o"}
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            result_count = _count_results(data) if data else 0
            success = False
            match_url = None

            if data and result_count > 0:
                # Validate the result actually matches the citation.
                matched_result = _match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = _extract_result_url(matched_result, base="https://www.courtlistener.com")

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
            result_count = _count_results(data) if data else 0
            success = False
            match_url = None

            if data and result_count > 0 and result_count <= 50:
                # Validate the result actually matches the citation.
                matched_result = _match_courtlistener_result(citation, data, base_citation)
                if matched_result is not None:
                    success = True
                    match_url = _extract_result_url(matched_result, base="https://www.courtlistener.com")

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

    def _verify_with_google_scholar(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Verify citation via Google Scholar case law search.

        Google Scholar's case law search at scholar.google.com/scholar?as_sdt=4
        returns HTML results. We search for the citation and check if the
        response contains matching case references.
        """
        if self._session is None:
            return None

        base_citation = strip_pincite(citation.normalized_citation)
        case_name = case_name_from_metadata(citation.metadata)
        target_triplet = reporter_triplet(base_citation)

        # Strategy 1: search by exact citation string
        strategies: List[Tuple[str, str]] = [
            ("scholar_citation", base_citation),
        ]
        # Strategy 2: case name + citation (if we have a case name)
        if case_name:
            strategies.append(("scholar_name_citation", f"{case_name} {base_citation}"))

        for strategy, query_text in strategies:
            scholar_url = (
                f"https://scholar.google.com/scholar"
                f"?as_sdt=4&q={quote_plus(query_text)}&hl=en"
            )

            success = False
            error = None
            match_url: Optional[str] = None

            try:
                response = self._session.get(
                    scholar_url,
                    timeout=self.request_timeout,
                    headers={"User-Agent": "legal-citation-checker/0.1"},
                )
                if response.status_code < 400:
                    body = response.text
                    # Check if the citation triplet or exact text appears in results
                    if base_citation in body:
                        success = True
                        match_url = scholar_url
                    elif target_triplet:
                        # Check for volume + page in results (reporter may be abbreviated differently)
                        vol, _, page = target_triplet
                        if f">{vol} " in body and f" {page}" in body:
                            success = True
                            match_url = scholar_url
                else:
                    error = f"HTTP {response.status_code}"
            except Exception as exc:
                error = str(exc)

            attempts.append(
                SearchAttempt(
                    source="Google Scholar",
                    strategy=strategy,
                    query=query_text,
                    success=success,
                    result_count=1 if success else 0,
                    url=match_url or scholar_url,
                    details="Citation found in Google Scholar results" if success else "No match in results",
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (Google Scholar)",
                    confidence=85,
                    source="Google Scholar",
                    source_url=match_url,
                    evidence=f"Google Scholar {strategy} search found a matching citation.",
                    search_attempts=attempts,
                )

        return None

    def _verify_with_web_docket_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Verify by searching the web for distinctive caption words + court.

        Real cases leave a web footprint on dockets, law firm sites, news, etc.
        Hallucinated cases have no web presence. We pick the most distinctive
        party name and combine it with the court to form a targeted query.
        """
        if self._session is None:
            return None

        case_name = case_name_from_metadata(citation.metadata)
        if not case_name:
            return None

        base_citation = strip_pincite(citation.normalized_citation)
        court = str(citation.metadata.get("court") or "")
        meta_year = str(citation.metadata.get("year") or "")

        # Pick the most distinctive word from the case name.
        # Skip common legal words and short words.
        _COMMON_WORDS = frozenset({
            "v", "vs", "the", "of", "in", "re", "ex", "rel", "et", "al",
            "state", "states", "united", "people", "city", "county",
            "board", "department", "commission", "inc", "corp", "llc", "ltd",
        })
        words = re.split(r"[\s\.\,]+", case_name)
        distinctive = [
            w for w in words
            if len(w) > 3 and w.lower() not in _COMMON_WORDS
        ]

        if not distinctive:
            return None

        # Use the longest word as the most distinctive identifier.
        keyword = max(distinctive, key=len)

        # Build search queries combining keyword + court/citation info.
        queries: List[Tuple[str, str]] = []

        if court:
            queries.append(("docket_keyword_court", f'"{keyword}" {court} case'))
        queries.append(("docket_keyword_citation", f'"{keyword}" "{base_citation}"'))
        if meta_year:
            queries.append(("docket_keyword_year", f'"{keyword}" case {meta_year}'))

        for strategy, query_text in queries:
            search_url = (
                f"https://www.google.com/search"
                f"?q={quote_plus(query_text)}"
            )

            success = False
            error = None
            match_url: Optional[str] = None

            try:
                response = self._session.get(
                    search_url,
                    timeout=self.request_timeout,
                    headers={"User-Agent": "legal-citation-checker/0.1"},
                )
                if response.status_code < 400:
                    body = response.text.lower()
                    # Check if the response contains indicators of a real case:
                    # - The citation text itself
                    # - Common legal docket indicators alongside our keyword
                    keyword_lower = keyword.lower()
                    base_lower = base_citation.lower()

                    has_citation = base_lower in body
                    has_keyword = keyword_lower in body
                    has_legal_context = any(
                        term in body for term in
                        ("docket", "opinion", "court", "ruling", "decided", "filed")
                    )

                    if has_citation and has_keyword:
                        success = True
                        match_url = search_url
                    elif has_keyword and has_legal_context:
                        success = True
                        match_url = search_url
                else:
                    error = f"HTTP {response.status_code}"
            except Exception as exc:
                error = str(exc)

            attempts.append(
                SearchAttempt(
                    source="Web Search",
                    strategy=strategy,
                    query=query_text,
                    success=success,
                    result_count=1 if success else 0,
                    url=match_url or search_url,
                    details="Case found via web docket search" if success else "No docket presence found",
                    error=error,
                )
            )

            if success:
                return VerificationDecision(
                    status="Verified (Web Search)",
                    confidence=75,
                    source="Web Search",
                    source_url=match_url,
                    evidence=f"Web search for '{query_text}' found case presence on the web.",
                    search_attempts=attempts,
                )

        return None

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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def strip_pincite(citation: str) -> str:
    """Strip pincite from citation: '347 U.S. 483, 495' -> '347 U.S. 483'."""
    m = _PINCITE_PATTERN.match(citation)
    return m.group(1).strip() if m else citation


def raw_reporter_from_citation(citation: str) -> str:
    """Extract the reporter string as-is from a citation like '56 Cal. 2d 407'."""
    m = re.search(r"\b\d{1,4}\s+(.+?)\s+\d{1,5}\b", citation)
    return m.group(1).strip() if m else ""


def reporter_triplet(citation: str) -> Optional[Tuple[str, str, str]]:
    """Extract (volume, reporter, page) tuple from a citation."""
    pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")
    match = pattern.search(citation)
    if not match:
        return None
    return (
        match.group(1),
        canonical_text(match.group(2)),
        match.group(3),
    )


def triplet_match(value: str, target: Tuple[str, str, str]) -> bool:
    """Check if a string contains the same reporter triplet as the target."""
    candidate = reporter_triplet(value)
    if candidate is None:
        return False
    return candidate == target


def case_name_from_metadata(metadata: Dict[str, Any]) -> str:
    """Build case name from metadata fields."""
    plaintiff = str(metadata.get("plaintiff") or "").strip()
    defendant = str(metadata.get("defendant") or "").strip()
    if plaintiff and defendant:
        return f"{plaintiff} v. {defendant}"

    for key in ("case_name", "name", "party_names"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _build_broad_query(citation: ExtractedCitation) -> str:
    case_name = case_name_from_metadata(citation.metadata)
    year = str(citation.metadata.get("year") or "")
    parts = [part for part in [case_name, citation.normalized_citation, year] if part]
    if not parts:
        return citation.normalized_citation
    return " ".join(parts)


def _build_triplet_query(citation: ExtractedCitation) -> Optional[Dict[str, str]]:
    triplet = reporter_triplet(citation.normalized_citation)
    if not triplet:
        return None
    volume, rep, page = triplet
    return {"q": f"{volume} {rep} {page}", "type": "o"}


def _count_results(data: Dict[str, Any]) -> int:
    count = data.get("count")
    if isinstance(count, int):
        return count
    results = data.get("results")
    if isinstance(results, list):
        return len(results)
    return 0


def _match_courtlistener_result(
    citation: ExtractedCitation,
    data: Dict[str, Any],
    base_citation: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    candidates = data.get("results")
    if not isinstance(candidates, list):
        return None

    target_text = base_citation or citation.normalized_citation
    normalized_target = canonical_text(target_text)
    target_triplet = reporter_triplet(target_text)
    meta_name = case_name_from_metadata(citation.metadata)
    meta_year = str(citation.metadata.get("year") or "")

    for result in candidates:
        if not isinstance(result, dict):
            continue

        # Check citation fields (varies by API response shape).
        result_citations = (
            result.get("citation")
            or result.get("citations")
            or []
        )
        if isinstance(result_citations, str):
            result_citations = [result_citations]
        if isinstance(result_citations, list):
            for value in result_citations:
                cite_str = value if isinstance(value, str) else (value.get("cite", "") if isinstance(value, dict) else "")
                if not cite_str:
                    continue
                if canonical_text(cite_str) == normalized_target:
                    return result
                if target_triplet and triplet_match(cite_str, target_triplet):
                    return result

        # Check if the citation appears anywhere in the snippet/text fields.
        for text_field in ("snippet", "text", "plain_text", "html"):
            text_value = result.get(text_field, "")
            if isinstance(text_value, str) and target_text in text_value:
                return result

        # Triplet match against caseName or cluster citation fields.
        case_name_val = str(result.get("caseName") or result.get("case_name") or result.get("caseNameFull") or "")
        date_filed = str(result.get("dateFiled") or result.get("date_filed") or result.get("dateArgued") or "")

        if target_triplet:
            for field_name in ("caseName", "case_name", "caseNameFull"):
                val = str(result.get(field_name, ""))
                if triplet_match(val, target_triplet):
                    return result

        # Fallback: name/year match.
        if meta_name and case_name_val:
            canonical_meta = canonical_text(meta_name)
            canonical_case = canonical_text(case_name_val)
            if canonical_meta and re.search(r"\b" + re.escape(canonical_meta) + r"\b", canonical_case):
                if not meta_year or meta_year in date_filed:
                    return result

    return None


def _extract_result_url(result: Any, base: str) -> Optional[str]:
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


def _hallucination_confidence(attempt_count: int) -> int:
    if attempt_count >= 6:
        return 92
    if attempt_count >= 4:
        return 90
    if attempt_count >= 3:
        return 85
    return 75


def _build_failure_evidence(attempts: Iterable[SearchAttempt]) -> str:
    parts = []
    for attempt in attempts:
        if attempt.success:
            continue
        err = f" ({attempt.error})" if attempt.error else ""
        parts.append(f"{attempt.source}:{attempt.strategy} failed{err}")

    if not parts:
        return "No verification evidence available."
    return "; ".join(parts)
