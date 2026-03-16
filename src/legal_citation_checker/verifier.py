"""Citation verification against CourtListener and secondary sources."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

from .models import ExtractedCitation, ParsedCitation, SearchAttempt, VerificationDecision
from .normalizer import canonical_text

logger = logging.getLogger("legal_citation_checker")

# Regex to strip pincites: "347 U.S. 483, 495" -> "347 U.S. 483"
_PINCITE_PATTERN = re.compile(r"^(.+?\d+)\s*,\s*\d+(?:\s*[-–]\s*\d+)?$")

# Regex to detect Westlaw citations: "2025 WL 2192378"
_WESTLAW_PATTERN = re.compile(r"^\d{4}\s+WL\s+\d+$", re.IGNORECASE)

# Regex to detect LexisNexis citations: "2024 U.S. App. LEXIS 12345"
_LEXIS_PATTERN = re.compile(r"^\d{4}\s+\S.*?\s*LEXIS\s+\d+$", re.IGNORECASE)

# CourtListener search API (v4 — the /search/ endpoint is free, no auth).
COURTLISTENER_SEARCH_BASE = "https://www.courtlistener.com/api/rest/v4/search/"


class CitationVerifier:
    """Verifies citations against CourtListener and secondary sources.

    Verification strategy:
      Tier 1 — Citation number lookup (foolproof if positive).
               CourtListener can be quirky about citation formats, so a
               negative result does NOT mean the citation is fake.
      Tier 2 — Party name search (requires fuzzy matching of results).
               Searches by plaintiff/defendant names, then judges whether
               the closest result actually matches our citation.
      Tier 3 — Google Scholar / web docket fallback.
      Final  — If all real "not found" → Potential Hallucination.
               If all network errors → Needs Review.
    """

    def __init__(self, session: Any, request_timeout: float = 8.0) -> None:
        self._session = session
        self.request_timeout = request_timeout

    def verify(self, citation: ExtractedCitation) -> VerificationDecision:
        """Run the full tiered verification pipeline for a citation."""
        attempts: List[SearchAttempt] = []
        p = citation.parsed

        # Detect vendor-specific citations (WL/Lexis) — these can't be
        # verified by citation number, but we CAN verify the underlying case
        # exists by searching for party names on CourtListener / Google Scholar.
        norm = citation.normalized_citation.strip()
        is_vendor_cite = bool(
            _WESTLAW_PATTERN.match(norm) or _LEXIS_PATTERN.match(norm)
        )

        if not is_vendor_cite:
            # ── Tier 1: Citation number lookup (foolproof if positive) ──
            decision = self._tier1_citation_lookup(citation, attempts)
            if decision is not None:
                return decision

        # ── Tier 2: Party name search (fuzzy match on results) ──────────
        decision = self._tier2_party_name_search(citation, attempts)
        if decision is not None:
            if is_vendor_cite:
                # Downgrade confidence slightly — we verified the case exists
                # but can't confirm the exact WL/Lexis number.
                decision.status = "Verified (case exists)"
                decision.confidence = min(decision.confidence, 80)
                decision.evidence = (
                    f"Case verified via party name search. "
                    f"The exact {'WL' if _WESTLAW_PATTERN.match(norm) else 'LEXIS'} "
                    f"citation number could not be independently confirmed. "
                    f"Original: {decision.evidence}"
                )
            return decision

        # ── Tier 3: Google Scholar ──────────────────────────────────────
        decision = self._tier3_google_scholar(citation, attempts)
        if decision is not None:
            if is_vendor_cite:
                decision.status = "Verified (case exists)"
                decision.confidence = min(decision.confidence, 75)
                decision.evidence = (
                    f"Case verified via Google Scholar. "
                    f"The exact {'WL' if _WESTLAW_PATTERN.match(norm) else 'LEXIS'} "
                    f"citation number could not be independently confirmed. "
                    f"Original: {decision.evidence}"
                )
            return decision

        # ── Tier 4: Web docket search ───────────────────────────────────
        decision = self._tier4_web_docket_search(citation, attempts)
        if decision is not None:
            if is_vendor_cite:
                decision.status = "Verified (case exists)"
                decision.confidence = min(decision.confidence, 70)
                decision.evidence = (
                    f"Case verified via web search. "
                    f"The exact {'WL' if _WESTLAW_PATTERN.match(norm) else 'LEXIS'} "
                    f"citation number could not be independently confirmed. "
                    f"Original: {decision.evidence}"
                )
            return decision

        # ── Final: vendor citation or hallucination ─────────────────────
        if is_vendor_cite:
            # Vendor citations that couldn't be verified via party names
            vendor = "WL" if _WESTLAW_PATTERN.match(norm) else "LEXIS"
            return VerificationDecision(
                status="Needs Review",
                confidence=0,
                evidence=f"{vendor} citation could not be verified: no matching case "
                         f"found via party name search on CourtListener, Google Scholar, "
                         f"or web search. Verify manually via {'Westlaw' if vendor == 'WL' else 'LexisNexis'}.",
                search_attempts=attempts,
            )

        # ── Final: Network error check vs. hallucination ────────────────
        non_skipped = [a for a in attempts if a.details != "skipped"]
        all_errored = non_skipped and all(a.error is not None for a in non_skipped)
        none_found = non_skipped and all(a.result_count == 0 for a in non_skipped)

        if all_errored and len(non_skipped) < 4:
            # Very few attempts and all errored — genuinely can't tell
            return VerificationDecision(
                status="Needs Review",
                confidence=0,
                evidence="All verification sources returned errors (network/API issues). "
                         "Cannot determine if citation is valid or fabricated.",
                search_attempts=attempts,
            )

        if none_found:
            # Enough sources tried and none returned results — likely fabricated
            confidence = _hallucination_confidence(len(attempts))
            return VerificationDecision(
                status="Potential Hallucination",
                confidence=confidence,
                evidence=_build_failure_evidence(attempts)
                         + (" All sources errored but none found any matching results." if all_errored else ""),
                search_attempts=attempts,
            )

        confidence = _hallucination_confidence(len(attempts))
        return VerificationDecision(
            status="Potential Hallucination",
            confidence=confidence,
            evidence=_build_failure_evidence(attempts),
            search_attempts=attempts,
        )

    # ─── Tier 1: Citation Number Lookup ─────────────────────────────────

    def _tier1_citation_lookup(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Search CourtListener by citation number using structured fields.

        Positive match is foolproof.  Negative is NOT conclusive — CL is
        quirky about how it indexes citation strings, so we always fall
        through to party name search on miss.
        """
        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)

        # Strategy 1: structured citation field
        if base:
            data, url, error = self._http_get_json(
                COURTLISTENER_SEARCH_BASE,
                params={"citation": base, "type": "o"},
            )
            success, match_url = self._check_results(citation, data, base)

            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy="citation_field",
                query=f"citation={base}",
                success=success,
                result_count=_count_results(data) if data else 0,
                url=match_url or url,
                details="Exact citation field match" if success else "No match via citation field",
                error=error,
            ))
            if success:
                return self._verified_decision(
                    "citation_field", match_url or url, 95, attempts
                )

        # Strategy 2: quoted citation in free-text q=
        if base:
            data, url, error = self._http_get_json(
                COURTLISTENER_SEARCH_BASE,
                params={"q": f'citation:"{base}"', "type": "o"},
            )
            success, match_url = self._check_results(citation, data, base)

            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy="citation_query",
                query=f'citation:"{base}"',
                success=success,
                result_count=_count_results(data) if data else 0,
                url=match_url or url,
                details="Quoted citation query match" if success else "No match via citation query",
                error=error,
            ))
            if success:
                return self._verified_decision(
                    "citation_query", match_url or url, 95, attempts
                )

        # Strategy 3: citation without periods (CL sometimes strips them)
        base_no_dots = base.replace(".", "") if base else ""
        if base_no_dots and base_no_dots != base:
            data, url, error = self._http_get_json(
                COURTLISTENER_SEARCH_BASE,
                params={"q": f'citation:"{base_no_dots}"', "type": "o"},
            )
            success, match_url = self._check_results(citation, data, base)

            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy="citation_no_periods",
                query=f'citation:"{base_no_dots}"',
                success=success,
                result_count=_count_results(data) if data else 0,
                url=match_url or url,
                details="No-periods citation match" if success else "No match without periods",
                error=error,
            ))
            if success:
                return self._verified_decision(
                    "citation_no_periods", match_url or url, 95, attempts
                )

        # Negative is NOT conclusive — fall through to party names.
        return None

    # ─── Tier 2: Party Name Search ──────────────────────────────────────

    def _tier2_party_name_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Search CourtListener by party names and judge closest result.

        Unlike citation lookup, party name search returns many results that
        need fuzzy matching.  We check if any result's citation list contains
        our target citation number.
        """
        p = citation.parsed
        case_name = p.case_name or case_name_from_metadata(citation.metadata)
        base = p.base_citation or strip_pincite(citation.normalized_citation)

        if not case_name:
            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy="party_name",
                query="",
                success=False,
                details="skipped",
                error=None,
            ))
            return None

        # Build date filters from year (fall back to metadata)
        year_str = p.year or str(citation.metadata.get("year") or "").strip() or None
        date_params: Dict[str, str] = {}
        if year_str:
            try:
                y = int(year_str)
                date_params["filed_after"] = f"{y - 1}-01-01"
                date_params["filed_before"] = f"{y + 1}-12-31"
            except ValueError:
                pass

        # Strategy 1: case_name structured field + date filter
        params: Dict[str, str] = {"case_name": case_name, "type": "o"}
        params.update(date_params)
        data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
        best = self._best_party_match(data, citation) if data else None

        attempts.append(SearchAttempt(
            source="CourtListener",
            strategy="party_name_field",
            query=f"case_name={case_name}",
            success=best is not None,
            result_count=_count_results(data) if data else 0,
            url=(best[1] if best else None) or url,
            details=f"Party match: {best[2]}" if best else "No party name match",
            error=error,
        ))
        if best is not None:
            return self._verified_decision(
                "party_name_field", best[1] or url, best[0], attempts
            )

        # Strategy 2: quoted full case name in free-text
        query_str = f'"{case_name}"'
        if date_params:
            for k, v in date_params.items():
                query_str += f" {k}:{v}"
        data, url, error = self._http_get_json(
            COURTLISTENER_SEARCH_BASE, params={"q": query_str, "type": "o"}
        )
        best = self._best_party_match(data, citation) if data else None

        attempts.append(SearchAttempt(
            source="CourtListener",
            strategy="party_name_quoted",
            query=query_str,
            success=best is not None,
            result_count=_count_results(data) if data else 0,
            url=(best[1] if best else None) or url,
            details=f"Quoted name match: {best[2]}" if best else "No match",
            error=error,
        ))
        if best is not None:
            return self._verified_decision(
                "party_name_quoted", best[1] or url, best[0], attempts
            )

        # Strategy 3: individual party names (plaintiff OR defendant)
        # Fall back to metadata for party names if parsed fields are empty
        plaintiff = p.plaintiff or str(citation.metadata.get("plaintiff") or "").strip() or None
        defendant = p.defendant or str(citation.metadata.get("defendant") or "").strip() or None
        for party_role, party_name in [("plaintiff", plaintiff), ("defendant", defendant)]:
            if not party_name or len(party_name) < 3:
                continue
            params = {"q": f'"{party_name}"', "type": "o"}
            params.update(date_params)
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            best = self._best_party_match(data, citation) if data else None

            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy=f"party_{party_role}",
                query=f'"{party_name}"',
                success=best is not None,
                result_count=_count_results(data) if data else 0,
                url=(best[1] if best else None) or url,
                details=f"{party_role} match: {best[2]}" if best else f"No {party_role} match",
                error=error,
            ))
            if best is not None:
                return self._verified_decision(
                    f"party_{party_role}", best[1] or url, best[0], attempts
                )

        return None

    def _best_party_match(
        self,
        data: Dict[str, Any],
        citation: ExtractedCitation,
    ) -> Optional[Tuple[int, Optional[str], str]]:
        """Judge which result (if any) is the closest match.

        Returns (confidence, url, reason) or None.

        Matching hierarchy:
          1. Result has our exact citation number → 90% confidence
          2. Result's case name contains both party names + year matches → 85%
          3. Result's case name matches + reporter triplet matches → 85%
        """
        results = data.get("results")
        if not isinstance(results, list):
            return None

        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        target_triplet = reporter_triplet(base) if base else None

        for result in results:
            if not isinstance(result, dict):
                continue

            result_url = _extract_result_url(result, base="https://www.courtlistener.com")

            # Check 1: Does this result contain our citation number?
            result_cites = _get_citation_strings(result)
            for cite_str in result_cites:
                if _citations_equivalent(cite_str, base, target_triplet):
                    return (90, result_url, f"citation {base} found in result")

            # Check 2: Case name match (token-based fuzzy + substring fallback)
            result_name = _get_case_name(result)
            result_date = str(result.get("dateFiled") or result.get("date_filed") or "")

            # Fall back to metadata for party names if parsed fields are empty
            plaintiff = p.plaintiff or str(citation.metadata.get("plaintiff") or "").strip() or None
            defendant = p.defendant or str(citation.metadata.get("defendant") or "").strip() or None
            year = p.year or str(citation.metadata.get("year") or "").strip() or None
            year_ok = (not year) or (year in result_date)

            # Build the cited case name for token comparison (used in Checks 2 & 3)
            cited_name = p.case_name or case_name_from_metadata(citation.metadata)

            if result_name:

                # Method A: Token-overlap matching (from smart-rename-legal)
                if cited_name:
                    overlap_ratio, overlap_count = _name_token_overlap(cited_name, result_name)
                    # Strong match: >= 50% overlap AND >= 2 tokens (or >= 80% with any tokens)
                    strong_token_match = (
                        (overlap_ratio >= 0.5 and overlap_count >= 2) or
                        overlap_ratio >= 0.8
                    )
                    if strong_token_match and year_ok:
                        if target_triplet:
                            for cite_str in result_cites:
                                if triplet_match(cite_str, target_triplet):
                                    return (90, result_url, f"token match ({overlap_count} tokens, {overlap_ratio:.0%}) + triplet")
                        return (85, result_url, f"token match ({overlap_count} tokens, {overlap_ratio:.0%}) + year")

                # Method B: Substring fallback for cases where only party names are available
                if plaintiff and defendant:
                    name_lower = result_name.lower()
                    has_plaintiff = plaintiff.lower() in name_lower
                    has_defendant = defendant.lower() in name_lower

                    if has_plaintiff and has_defendant and year_ok:
                        if target_triplet:
                            for cite_str in result_cites:
                                if triplet_match(cite_str, target_triplet):
                                    return (85, result_url, f"parties + triplet match")
                        return (85, result_url, f"parties ({plaintiff}, {defendant}) + year match")

                    # Method C: Single party + token overlap (weaker but still useful)
                    if (has_plaintiff or has_defendant) and year_ok and cited_name:
                        overlap_ratio, overlap_count = _name_token_overlap(cited_name, result_name)
                        if overlap_ratio >= 0.4 and overlap_count >= 1:
                            matched_party = plaintiff if has_plaintiff else defendant
                            return (75, result_url, f"party '{matched_party}' + token overlap ({overlap_ratio:.0%})")

            # Check 3: Reporter triplet in result citations
            if target_triplet:
                for cite_str in result_cites:
                    if triplet_match(cite_str, target_triplet):
                        # Triplet matches — verify name isn't wildly different
                        if result_name and cited_name:
                            overlap_ratio, _ = _name_token_overlap(cited_name, result_name)
                            if overlap_ratio >= 0.3:
                                return (85, result_url, f"triplet + name overlap ({overlap_ratio:.0%})")
                        elif result_name and plaintiff:
                            if plaintiff.lower() in result_name.lower():
                                return (85, result_url, "triplet + plaintiff match")
                        # Triplet alone is decent evidence
                        return (80, result_url, "reporter triplet match in results")

        return None

    # ─── Tier 3: Google Scholar ─────────────────────────────────────────

    def _tier3_google_scholar(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Verify via Google Scholar case law search."""
        if self._session is None:
            return None

        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        case_name = p.case_name or case_name_from_metadata(citation.metadata)
        target_triplet = reporter_triplet(base) if base else None

        strategies: List[Tuple[str, str]] = [("scholar_citation", base)]
        if case_name:
            strategies.append(("scholar_name_citation", f"{case_name} {base}"))

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
                    if base in body:
                        success = True
                        match_url = scholar_url
                    elif target_triplet:
                        vol, _, page = target_triplet
                        if f">{vol} " in body and f" {page}" in body:
                            success = True
                            match_url = scholar_url
                else:
                    error = f"HTTP {response.status_code}"
            except Exception as exc:
                error = str(exc)

            attempts.append(SearchAttempt(
                source="Google Scholar",
                strategy=strategy,
                query=query_text,
                success=success,
                result_count=1 if success else 0,
                url=match_url or scholar_url,
                details="Citation found in Scholar results" if success else "No match",
                error=error,
            ))
            if success:
                return VerificationDecision(
                    status="Verified (Google Scholar)",
                    confidence=85,
                    source="Google Scholar",
                    source_url=match_url,
                    evidence=f"Google Scholar {strategy} found a matching citation.",
                    search_attempts=attempts,
                )

        return None

    # ─── Tier 4: Web Docket Search ──────────────────────────────────────

    def _tier4_web_docket_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Search web for distinctive caption word + court name."""
        if self._session is None:
            return None

        p = citation.parsed
        case_name = p.case_name or case_name_from_metadata(citation.metadata)
        if not case_name:
            return None

        base = p.base_citation or strip_pincite(citation.normalized_citation)
        court = p.court or str(citation.metadata.get("court") or "")
        year = p.year or str(citation.metadata.get("year") or "")

        keyword = _most_distinctive_word(case_name)
        if not keyword:
            return None

        queries: List[Tuple[str, str]] = []
        if court:
            queries.append(("docket_keyword_court", f'"{keyword}" {court} case'))
        queries.append(("docket_keyword_citation", f'"{keyword}" "{base}"'))
        if year:
            queries.append(("docket_keyword_year", f'"{keyword}" case {year}'))

        for strategy, query_text in queries:
            search_url = f"https://www.google.com/search?q={quote_plus(query_text)}"
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
                    keyword_lower = keyword.lower()
                    base_lower = base.lower()

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

            attempts.append(SearchAttempt(
                source="Web Search",
                strategy=strategy,
                query=query_text,
                success=success,
                result_count=1 if success else 0,
                url=match_url or search_url,
                details="Case found via web search" if success else "No web presence found",
                error=error,
            ))
            if success:
                return VerificationDecision(
                    status="Verified (Web Search)",
                    confidence=75,
                    source="Web Search",
                    source_url=match_url,
                    evidence=f"Web search for '{query_text}' found case presence.",
                    search_attempts=attempts,
                )

        return None

    # ─── Shared helpers ─────────────────────────────────────────────────

    def _check_results(
        self,
        citation: ExtractedCitation,
        data: Optional[Dict[str, Any]],
        base_citation: str,
    ) -> Tuple[bool, Optional[str]]:
        """Check if API response contains a matching result."""
        if data is None:
            return False, None
        matched = _match_courtlistener_result(citation, data, base_citation)
        if matched is None:
            return False, None
        url = _extract_result_url(matched, base="https://www.courtlistener.com")
        return True, url

    def _verified_decision(
        self,
        strategy: str,
        url: Optional[str],
        confidence: int,
        attempts: List[SearchAttempt],
    ) -> VerificationDecision:
        return VerificationDecision(
            status="Verified (CourtListener)",
            confidence=confidence,
            source="CourtListener",
            source_url=url,
            evidence=f"CourtListener {strategy} returned a matching result.",
            search_attempts=attempts,
        )

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
        if isinstance(data, list):
            return {"count": len(data), "results": data}, request_url, None
        return None, request_url, "Unexpected response type"

    # Backward-compat aliases used by old verifier methods and Google Scholar/web search
    def _verify_with_google_scholar(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        return self._tier3_google_scholar(citation, attempts)

    def _verify_with_web_docket_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        return self._tier4_web_docket_search(citation, attempts)


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
    """Extract (volume, canonical_reporter, page) tuple from a citation."""
    pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")
    match = pattern.search(citation)
    if not match:
        return None
    return (match.group(1), canonical_text(match.group(2)), match.group(3))


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
    return " ".join(parts) if parts else citation.normalized_citation


def _most_distinctive_word(case_name: str) -> Optional[str]:
    """Pick the most distinctive word from a case name for web searching."""
    words = re.split(r"[\s\.\,]+", case_name)
    distinctive = [w for w in words if len(w) > 3 and w.lower() not in _NAME_NOISE_WORDS]
    if not distinctive:
        return None
    return max(distinctive, key=len)


# Noise words filtered from case names during token-based matching.
# Ported from smart-rename-legal's matching logic.
_NAME_NOISE_WORDS = frozenset({
    "v", "vs", "the", "of", "in", "re", "ex", "rel", "et", "al", "a", "an",
    "for", "on", "by", "to", "and", "or", "no", "nos",
    # Common entity suffixes
    "inc", "corp", "co", "llc", "llp", "ltd", "lp", "pa", "pc", "pllc",
    "assn", "ass'n", "assoc", "association",
    # Government / generic parties
    "state", "states", "united", "people", "city", "county", "town",
    "board", "department", "dept", "commission", "authority", "agency",
    "government", "gov", "govt",
    # Procedural
    "matter", "estate", "interest", "application", "petition",
})


def _extract_name_tokens(name: str) -> set:
    """Extract meaningful tokens from a case name, filtering noise words.

    Ported from smart-rename-legal's token-overlap matching approach.
    Returns a set of lowercased tokens suitable for overlap comparison.
    """
    # Split on whitespace, punctuation, and common separators
    raw_tokens = re.split(r"[\s\.\,\;\:\(\)\[\]\-/]+", name)
    tokens = set()
    for t in raw_tokens:
        # Strip possessives and trailing punctuation
        t = re.sub(r"['']s$", "", t).strip("'\"")
        low = t.lower()
        if len(low) >= 2 and low not in _NAME_NOISE_WORDS:
            tokens.add(low)
    return tokens


def _name_token_overlap(name_a: str, name_b: str) -> Tuple[float, int]:
    """Compute token overlap ratio between two case names.

    Returns (overlap_ratio, num_matching_tokens).
    overlap_ratio is relative to the smaller token set.
    """
    tokens_a = _extract_name_tokens(name_a)
    tokens_b = _extract_name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return (0.0, 0)
    common = tokens_a & tokens_b
    smaller = min(len(tokens_a), len(tokens_b))
    return (len(common) / smaller, len(common))


def _count_results(data: Dict[str, Any]) -> int:
    count = data.get("count")
    if isinstance(count, int):
        return count
    results = data.get("results")
    if isinstance(results, list):
        return len(results)
    return 0


def _get_citation_strings(result: Dict[str, Any]) -> List[str]:
    """Extract all citation strings from a CourtListener result."""
    raw = result.get("citation") or result.get("citations") or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                cite = item.get("cite", "")
                if cite:
                    out.append(cite)
        return out
    return []


def _get_case_name(result: Dict[str, Any]) -> str:
    """Extract case name from a CourtListener result."""
    for key in ("caseName", "case_name", "caseNameFull", "case_name_full"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _citations_equivalent(
    cite_str: str,
    target: str,
    target_triplet: Optional[Tuple[str, str, str]],
) -> bool:
    """Check if two citation strings refer to the same case."""
    if canonical_text(cite_str) == canonical_text(target):
        return True
    if target_triplet and triplet_match(cite_str, target_triplet):
        return True
    return False


def _match_courtlistener_result(
    citation: ExtractedCitation,
    data: Dict[str, Any],
    base_citation: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find a matching result in CourtListener response data."""
    candidates = data.get("results")
    if not isinstance(candidates, list):
        return None

    target_text = base_citation or citation.normalized_citation
    normalized_target = canonical_text(target_text)
    target_triplet = reporter_triplet(target_text)
    meta_name = citation.parsed.case_name or case_name_from_metadata(citation.metadata)
    meta_year = citation.parsed.year or str(citation.metadata.get("year") or "")

    for result in candidates:
        if not isinstance(result, dict):
            continue

        # Check citation fields
        for cite_str in _get_citation_strings(result):
            if _citations_equivalent(cite_str, target_text, target_triplet):
                return result

        # Check snippet/text fields
        for text_field in ("snippet", "text", "plain_text", "html"):
            text_value = result.get(text_field, "")
            if isinstance(text_value, str) and target_text in text_value:
                return result

        # Triplet match against case name fields
        if target_triplet:
            for field_name in ("caseName", "case_name", "caseNameFull"):
                val = str(result.get(field_name, ""))
                if triplet_match(val, target_triplet):
                    return result

        # Fallback: name/year match
        result_name = _get_case_name(result)
        result_date = str(result.get("dateFiled") or result.get("date_filed") or "")
        if meta_name and result_name:
            canonical_meta = canonical_text(meta_name)
            canonical_case = canonical_text(result_name)
            if canonical_meta and re.search(
                r"\b" + re.escape(canonical_meta) + r"\b", canonical_case
            ):
                if not meta_year or meta_year in result_date:
                    return result

    return None


def _extract_result_url(result: Any, base: str) -> Optional[str]:
    if isinstance(result, dict):
        for key in ("absolute_url", "frontend_url", "url", "case_url", "resource_uri", "id"):
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
    return "; ".join(parts) if parts else "No verification evidence available."
