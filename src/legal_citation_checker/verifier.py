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
      Tier 1  — Citation number lookup (foolproof if positive).
                CourtListener can be quirky about citation formats, so a
                negative result does NOT mean the citation is fake.
      Tier 2  — Party name search in opinions (requires fuzzy matching).
                Searches by plaintiff/defendant names, then judges whether
                the closest result actually matches our citation.
      Tier 2b — CourtListener docket search (type=d).
                Many state court cases have docket entries but no indexed
                opinion.  This catches those.
      Tier 3  — Google Scholar / web docket fallback.
      Final   — If all real "not found" → Potential Hallucination.
                If all network errors → Needs Review.
    """

    def __init__(
        self,
        session: Any,
        request_timeout: float = 8.0,
        api_token: Optional[str] = None,
    ) -> None:
        self._session = session
        self.request_timeout = request_timeout
        self._api_token = api_token or None

    def verify(self, citation: ExtractedCitation) -> VerificationDecision:
        """Run the full tiered verification pipeline for a citation."""
        attempts: List[SearchAttempt] = []
        p = citation.parsed

        # CACI: California Civil Jury Instructions — verify by number range
        if citation.citation_type == "CACICitation":
            return self._verify_caci(citation)

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

        # ── Tier 1b: uslaw.link (federal citation resolver) ─────────────
        decision = self._tier1b_uslaw_link(citation, attempts)
        if decision is not None:
            return decision

        # For Tiers 2-4b: return immediately on Verified; save Needs Review
        # as fallback so Tier 5 (Westlaw/Lexis) still gets a chance to reach
        # a definitive conclusion.
        unconfirmed_fallback: Optional[VerificationDecision] = None

        def _handle(d: Optional[VerificationDecision], vendor_confidence: int, vendor_source: str) -> Optional[VerificationDecision]:
            """Return decision if Verified, else save as fallback and return None."""
            nonlocal unconfirmed_fallback
            if d is None:
                return None
            if is_vendor_cite:
                d.status = "Verified (case exists)"
                d.confidence = min(d.confidence, vendor_confidence)
                d.evidence = (
                    f"Case verified via {vendor_source}. "
                    f"The exact {'WL' if _WESTLAW_PATTERN.match(norm) else 'LEXIS'} "
                    f"citation number could not be independently confirmed. "
                    f"Original: {d.evidence}"
                )
            if d.status.startswith("Verified") and d.confidence >= 75:
                return d
            # Low-confidence or non-Verified: save as fallback, let Tier 5 try
            if unconfirmed_fallback is None:
                unconfirmed_fallback = d
            return None

        # ── Tier 2: Party name search (fuzzy match on results) ──────────
        result = _handle(self._tier2_party_name_search(citation, attempts), 80, "party name search")
        if result is not None:
            return result

        # ── Tier 2b: CourtListener docket search (type=d) ────────────
        result = _handle(self._tier2b_docket_search(citation, attempts), 75, "docket search")
        if result is not None:
            return result

        # ── Tier 3: Google Scholar ──────────────────────────────────────
        result = _handle(self._tier3_google_scholar(citation, attempts), 75, "Google Scholar")
        if result is not None:
            return result

        # ── Tier 4: Brave Search API ────────────────────────────────────
        result = _handle(self._tier4_brave_search(citation, attempts), 75, "Brave Search")
        if result is not None:
            return result

        # ── Tier 4b: Web docket search ──────────────────────────────────
        result = _handle(self._tier4_web_docket_search(citation, attempts), 70, "web search")
        if result is not None:
            return result

        # ── Tier 5: Westlaw/Lexis escalation ───────────────────────────
        # Fires when all other tiers couldn't produce a Verified decision.
        decision = self._tier5_legal_research(citation, attempts)
        if decision is not None:
            return decision

        # If Tier 5 was skipped/errored, consider returning the best unconfirmed
        # result we saved rather than going straight to Hallucination.
        if unconfirmed_fallback is not None:
            # Never return a "Verified" status from fallback — all authoritative
            # tiers failed to confirm this citation.  Downgrade to Needs Review.
            if unconfirmed_fallback.status.startswith("Verified"):
                unconfirmed_fallback.status = "Needs Review"
                unconfirmed_fallback.confidence = min(unconfirmed_fallback.confidence, 50)
                unconfirmed_fallback.evidence = (
                    "No authoritative source confirmed this citation. "
                    "Best candidate found but not verified. "
                    + unconfirmed_fallback.evidence
                )
            # If the fallback is very weak (low-confidence party-name-only match
            # with no triplet anchor) AND many strategies already failed, the
            # fallback is noise — a common name found in an unrelated case.
            # In this situation "Potential Hallucination" is more accurate than
            # "Needs Review", which implies there is real evidence the case exists.
            real_attempts = [a for a in attempts if a.details != "skipped"]
            if unconfirmed_fallback.confidence <= 55 and len(real_attempts) >= 10:
                # Fall through to the Potential Hallucination verdict below.
                pass
            else:
                return unconfirmed_fallback

        # ── Final: vendor citation or hallucination ─────────────────────
        if is_vendor_cite:
            # Vendor citations that couldn't be verified via party names.
            # If we tried enough strategies and found nothing, treat as hallucination.
            vendor = "WL" if _WESTLAW_PATTERN.match(norm) else "LEXIS"
            real_attempts_v = [a for a in attempts if a.details != "skipped"]
            if len(real_attempts_v) >= 6:
                confidence = _hallucination_confidence(len(attempts))
                return VerificationDecision(
                    status="Potential Hallucination",
                    confidence=confidence,
                    evidence=f"{vendor} citation: no matching case found after "
                             f"{len(real_attempts_v)} search strategies. "
                             f"Party name search on CourtListener, Google Scholar, "
                             f"and web search all returned no match. "
                             f"Citation appears fabricated.",
                    search_attempts=attempts,
                )
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

    # ─── CACI Verification ───────────────────────────────────────────────

    def _verify_caci(self, citation: ExtractedCitation) -> VerificationDecision:
        """Verify CACI citation by checking number against valid ranges.

        Judicial Council publishes CACI Nos. 100–5099.
        """
        caci_num_str = str(citation.metadata.get("caci_number") or "").strip()
        try:
            caci_num = int(caci_num_str)
        except (ValueError, TypeError):
            return VerificationDecision(
                status="Needs Review",
                confidence=0,
                evidence=f"Could not parse CACI number: {caci_num_str!r}",
            )

        if 100 <= caci_num <= 5099:
            return VerificationDecision(
                status="Verified (CACI)",
                confidence=95,
                source="Judicial Council of California",
                evidence=f"CACI No. {caci_num} is within the valid published range (100–5099).",
            )
        return VerificationDecision(
            status="Potential Hallucination",
            confidence=90,
            evidence=f"CACI No. {caci_num} is outside the valid published range (100–5099).",
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

            # Citation found in CL but belongs to a completely different case.
            # Stop here — do NOT let Brave/web search verify citation numbers
            # alone and return "Verified" for a misattributed citation.
            actual_name = _citation_found_wrong_case(citation, data, base)
            if actual_name:
                meta_name = citation.parsed.case_name or case_name_from_metadata(citation.metadata)
                confidence = _hallucination_confidence(len(attempts))
                return VerificationDecision(
                    status="Potential Hallucination",
                    confidence=confidence,
                    evidence=(
                        f"Citation {base} exists in CourtListener but is attributed "
                        f"to '{meta_name}' — the actual case at this citation is "
                        f"'{actual_name}'. The case name appears to be fabricated or "
                        f"misattributed."
                    ),
                    search_attempts=attempts,
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

    # ─── Tier 2b: CourtListener Docket Search ────────────────────────────

    def _tier2b_docket_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Search CourtListener dockets (type=d) for cases not in opinions DB.

        Many state court cases (especially NY, CA) and recently filed cases
        have docket entries but no indexed opinion.  This tier catches those.
        """
        p = citation.parsed
        case_name = p.case_name or case_name_from_metadata(citation.metadata)
        if not case_name:
            return None

        # Build date filters from year
        year_str = p.year or str(citation.metadata.get("year") or "").strip() or None
        date_params: Dict[str, str] = {}
        if year_str:
            try:
                y = int(year_str)
                date_params["filed_after"] = f"{y - 1}-01-01"
                date_params["filed_before"] = f"{y + 1}-12-31"
            except ValueError:
                pass

        # Strategy: case_name in docket search
        params: Dict[str, str] = {"q": f'"{case_name}"', "type": "d"}
        params.update(date_params)
        data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
        best = self._best_docket_match(data, citation) if data else None

        attempts.append(SearchAttempt(
            source="CourtListener",
            strategy="docket_name",
            query=f'"{case_name}" type=d',
            success=best is not None,
            result_count=_count_results(data) if data else 0,
            url=(best[1] if best else None) or url,
            details=f"Docket match: {best[2]}" if best else "No docket match",
            error=error,
        ))
        if best is not None:
            return self._verified_decision(
                "docket_name", best[1] or url, best[0], attempts
            )

        # Strategy 2: individual party name in docket search
        plaintiff = p.plaintiff or str(citation.metadata.get("plaintiff") or "").strip() or None
        defendant = p.defendant or str(citation.metadata.get("defendant") or "").strip() or None
        for party_role, party_name in [("plaintiff", plaintiff), ("defendant", defendant)]:
            if not party_name or len(party_name) < 3:
                continue
            params = {"q": f'"{party_name}"', "type": "d"}
            params.update(date_params)
            data, url, error = self._http_get_json(COURTLISTENER_SEARCH_BASE, params=params)
            best = self._best_docket_match(data, citation) if data else None

            attempts.append(SearchAttempt(
                source="CourtListener",
                strategy=f"docket_{party_role}",
                query=f'"{party_name}" type=d',
                success=best is not None,
                result_count=_count_results(data) if data else 0,
                url=(best[1] if best else None) or url,
                details=f"Docket {party_role} match: {best[2]}" if best else f"No docket {party_role} match",
                error=error,
            ))
            if best is not None:
                return self._verified_decision(
                    f"docket_{party_role}", best[1] or url, best[0], attempts
                )

        return None

    def _best_docket_match(
        self,
        data: Dict[str, Any],
        citation: ExtractedCitation,
    ) -> Optional[Tuple[int, Optional[str], str]]:
        """Judge if any docket result matches our citation.

        Docket results don't have citation lists, so matching relies on
        case name fuzzy matching + year.  Lower confidence than opinion matches.

        To guard against "real name, wrong citation" hallucinations, when a
        docket match is found we do a follow-up opinion lookup on the matched
        case name to verify the citation number actually exists for that case.
        """
        results = data.get("results") or []
        if not results:
            return None

        p = citation.parsed
        cited_name = p.case_name or case_name_from_metadata(citation.metadata)
        year = p.year or str(citation.metadata.get("year") or "").strip() or None
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        target_triplet = reporter_triplet(base) if base else None

        for result in results[:10]:
            # Docket results use "caseName" or "case_name"
            result_name = (
                result.get("caseName")
                or result.get("case_name")
                or result.get("caseNameFull")
                or ""
            )
            result_date = str(result.get("dateFiled") or result.get("date_filed") or "")
            year_ok = (not year) or (year in result_date)

            docket_url = None
            docket_id = result.get("docket_id") or result.get("id")
            abs_url = result.get("absolute_url") or ""
            if abs_url:
                docket_url = f"https://www.courtlistener.com{abs_url}"
            elif docket_id:
                docket_url = f"https://www.courtlistener.com/docket/{docket_id}/"

            if not result_name or not cited_name:
                continue

            overlap_ratio, overlap_count = _name_token_overlap(cited_name, result_name)

            # Strong match: good token overlap + year
            # Require at least 2 overlapping tokens to avoid false positives
            # from common single-word names (Smith, Jones, etc.)
            matched = False
            if (overlap_ratio >= 0.5 and overlap_count >= 2) and year_ok:
                matched = True
            elif overlap_ratio >= 0.8 and overlap_count >= 2:
                matched = True

            if matched:
                # Cross-check: look up the matched case by name in opinions
                # to verify the citation number actually belongs to this case.
                if target_triplet and result_name:
                    verify_data, _, _ = self._http_get_json(
                        COURTLISTENER_SEARCH_BASE,
                        params={"case_name": result_name, "type": "o"},
                    )
                    if verify_data:
                        verify_results = verify_data.get("results") or []
                        for vr in verify_results[:5]:
                            vr_cites = _get_citation_strings(vr)
                            if vr_cites:
                                # This case has known citations — check if ours is among them
                                has_our_cite = any(
                                    _citations_equivalent(cs, base, target_triplet)
                                    for cs in vr_cites
                                )
                                if not has_our_cite:
                                    # Case exists under different citation — wrong cite
                                    logger.debug(
                                        f"Docket match for '{result_name}' rejected: "
                                        f"case exists but citation {base} not found in "
                                        f"known citations {vr_cites}"
                                    )
                                    return None  # reject — likely wrong citation number

                conf = 80 if year_ok else 75
                reason = f"docket token match ({overlap_count} tokens, {overlap_ratio:.0%})"
                if year_ok:
                    reason += " + year"
                return (conf, docket_url, reason)

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
                    # Single-token matches without a confirmable citation triplet are
                    # too ambiguous — common names (Barton, Smith) appear in many cases.
                    # Require >= 2 unique tokens OR a triplet to anchor the match.
                    if strong_token_match and overlap_count < 2 and not target_triplet:
                        strong_token_match = False
                    if strong_token_match and year_ok:
                        if target_triplet:
                            for cite_str in result_cites:
                                if triplet_match(cite_str, target_triplet):
                                    return (90, result_url, f"token match ({overlap_count} tokens, {overlap_ratio:.0%}) + triplet")
                        # If the result HAS citations but none match ours,
                        # the case exists but the citation number is wrong —
                        # a common LLM hallucination pattern.
                        if result_cites and target_triplet:
                            # Case name matches but citation doesn't — likely wrong cite
                            return None  # skip; will be caught as mismatch below
                        # Name matches but no citation data to confirm the number.
                        # Return lower confidence — name-only, unconfirmed.
                        if target_triplet and not result_cites:
                            return (60, result_url, f"token match ({overlap_count} tokens) — citation number unconfirmed")
                        # No triplet (e.g. WL citation): can't confirm the citation number
                        # via CourtListener. Cap at 60% to trigger Tier 5 escalation.
                        if not target_triplet:
                            return (60, result_url, f"token match ({overlap_count} tokens, {overlap_ratio:.0%}) — WL/vendor number unconfirmed")
                        return (85, result_url, f"token match ({overlap_count} tokens, {overlap_ratio:.0%}) + year")

                # Method B: Substring fallback for cases where only party names are available
                if plaintiff and defendant:
                    name_lower = result_name.lower()
                    p_lower = plaintiff.lower()
                    d_lower = defendant.lower()
                    has_plaintiff = p_lower in name_lower
                    has_defendant = d_lower in name_lower

                    # Symmetric names (e.g. "Barton v. Barton"): a single occurrence
                    # in the result name could be any case involving that party.
                    # Split on "v." and verify the name appears on BOTH sides.
                    # If only one side matches, zero out BOTH so Method C also skips.
                    if p_lower == d_lower and has_plaintiff:
                        v_parts = re.split(r"\s+v\.?\s+", name_lower, maxsplit=1, flags=re.IGNORECASE)
                        if len(v_parts) == 2 and p_lower in v_parts[0] and p_lower in v_parts[1]:
                            has_plaintiff = True
                            has_defendant = True
                        else:
                            # Partial or no match — zero both so Methods B and C skip
                            has_plaintiff = False
                            has_defendant = False

                    if has_plaintiff and has_defendant and year_ok:
                        if target_triplet:
                            for cite_str in result_cites:
                                if triplet_match(cite_str, target_triplet):
                                    return (85, result_url, f"parties + triplet match")
                        # If result has citations but none match, case exists
                        # under a different citation — wrong cite hallucination.
                        if result_cites and target_triplet:
                            return None
                        # No triplet (WL/vendor cite): both party names match but the
                        # citation number itself cannot be confirmed.  Common names like
                        # "Gonzalez" or "Perez" appear in thousands of cases — a substring
                        # hit is not strong enough to verify.  Cap well below the 75%
                        # gate so Tier 5 (Lexis/Westlaw) must confirm.
                        if not target_triplet:
                            return (55, result_url, f"parties ({plaintiff}, {defendant}) + year match — WL/vendor number unconfirmed")
                        # Both parties match + triplet is set but result_cites is empty
                        # (CL result has no normalized citations to cross-check).
                        # Lower to 65% so Tier 5 runs rather than returning Verified.
                        return (65, result_url, f"parties ({plaintiff}, {defendant}) + year match — citation number unconfirmed")

                    # Method C: Single party + token overlap (weaker but still useful)
                    if (has_plaintiff or has_defendant) and year_ok and cited_name:
                        overlap_ratio, overlap_count = _name_token_overlap(cited_name, result_name)
                        if overlap_ratio >= 0.4 and overlap_count >= 1:
                            matched_party = plaintiff if has_plaintiff else defendant
                            # No triplet: single-party match is very weak evidence.
                            # Cap below threshold so Tier 5 must confirm.
                            if not target_triplet:
                                return (35, result_url, f"party '{matched_party}' + token overlap ({overlap_ratio:.0%}) — WL/vendor number unconfirmed")
                            # Result has citations but none match our triplet → wrong cite.
                            if result_cites and not any(triplet_match(c, target_triplet) for c in result_cites):
                                return None
                            # No citations in CL result to cross-check the triplet.
                            # A single-party name match is too weak to verify a specific
                            # citation — many cases share one party name.  Reject so
                            # the pipeline reaches a Potential Hallucination verdict.
                            if not result_cites:
                                return None
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

    # ─── Tier 1b: uslaw.link ────────────────────────────────────────────

    def _tier1b_uslaw_link(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Verify via uslaw.link — a free federal citation resolver.

        Returns non-empty JSON array on hit, [] on miss.
        Also catches case-name misattribution: if the citation resolves but
        the returned title doesn't match our case name, flag as Potential
        Hallucination (same pattern as the CourtListener wrong-case check).

        Skips vendor cites (WL/Lexis) — uslaw.link only handles reporter cites.
        """
        if self._session is None:
            return None

        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        if not base:
            return None

        is_vendor = bool(_WESTLAW_PATTERN.match(base) or _LEXIS_PATTERN.match(base))
        if is_vendor:
            return None

        USLAW_URL = "https://uslaw.link/citation/find"
        success = False
        error = None
        match_url = None
        returned_title = ""
        raw_data: list = []

        try:
            resp = self._session.get(
                USLAW_URL,
                params={"text": base},
                timeout=self.request_timeout,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                raw_data = resp.json() if isinstance(resp.json(), list) else []
                if raw_data:
                    result = raw_data[0]
                    returned_title = result.get("title") or ""
                    reporter_obj = result.get("reporter") or {}
                    rid = reporter_obj.get("id") or ""
                    # Prefer CourtListener deep link if available
                    links = reporter_obj.get("links") or {}
                    cl_link = (links.get("courtlistener") or {}).get("html") or ""
                    if cl_link:
                        match_url = cl_link
                    elif rid:
                        match_url = f"https://uslaw.link/{rid}"
                    success = True
            elif resp.status_code >= 400:
                error = f"HTTP {resp.status_code}"
        except Exception as exc:
            error = str(exc)

        # Case-name mismatch check — same logic as CourtListener wrong-case guard
        cited_name = p.case_name or case_name_from_metadata(citation.metadata)
        if success and returned_title and cited_name:
            overlap_ratio, overlap_count = _name_token_overlap(cited_name, returned_title)
            if overlap_ratio < 0.2 and overlap_count == 0:
                attempts.append(SearchAttempt(
                    source="uslaw.link",
                    strategy="uslaw_citation",
                    query=base,
                    success=False,
                    result_count=1,
                    url=match_url or USLAW_URL,
                    details=f"Citation exists but case name mismatch: returned '{returned_title}'",
                    error=None,
                ))
                confidence = _hallucination_confidence(len(attempts))
                return VerificationDecision(
                    status="Potential Hallucination",
                    confidence=confidence,
                    evidence=(
                        f"Citation {base} resolves via uslaw.link to '{returned_title}', "
                        f"not '{cited_name}'. The case name appears fabricated or misattributed."
                    ),
                    search_attempts=attempts,
                )

        attempts.append(SearchAttempt(
            source="uslaw.link",
            strategy="uslaw_citation",
            query=base,
            success=success,
            result_count=1 if success else 0,
            url=match_url or USLAW_URL,
            details=(
                f"Citation resolved to '{returned_title}'" if success
                else ("Citation not found in uslaw.link" if not error else f"Error: {error}")
            ),
            error=error,
        ))

        if success:
            evidence = f"uslaw.link resolved {base}"
            if returned_title:
                evidence += f" → '{returned_title}'"
            return VerificationDecision(
                status="Verified (uslaw.link)",
                confidence=90,
                source="uslaw.link",
                source_url=match_url,
                evidence=evidence,
                search_attempts=attempts,
            )

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

        is_vendor = bool(_WESTLAW_PATTERN.match(base) or _LEXIS_PATTERN.match(base))

        # WL/Lexis cites: Scholar doesn't index proprietary vendor numbers —
        # any hit is just Scholar echoing our query. Skip Scholar entirely;
        # rely on party name search (Tiers 2-2b) and Tier 5 (Lexis/Westlaw).
        if is_vendor:
            return None

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
                    body_lower = body.lower()
                    if target_triplet:
                        # Require the full citation string (volume + reporter + page)
                        # to appear together in the body.  Checking volume and page
                        # separately is too loose — both can appear as unrelated numbers.
                        vol, rep, page = target_triplet
                        full_cite = f"{vol} {rep} {page}"
                        citation_found = full_cite.lower() in body_lower
                        # Also accept without periods for variants like "F4th"
                        alt_rep = rep.replace(".", "")
                        citation_found = citation_found or f"{vol} {alt_rep} {page}".lower() in body_lower
                    else:
                        # No standard triplet (IL App, etc.): require 4+ occurrences.
                        citation_found = body.count(base) >= 4

                    # Cross-check case name: require at least one party token to
                    # appear in the Scholar results.  This catches the pattern of
                    # a real citation number belonging to a different case — a
                    # fabricated "Smith v. Jones, 102 F.4th 456" fails if Scholar's
                    # result for "102 F.4th 456" shows a completely different case.
                    if citation_found and case_name:
                        name_tokens = _extract_name_tokens(case_name)
                        if name_tokens:
                            name_found = any(
                                tok in body_lower for tok in name_tokens
                                if len(tok) > 3  # skip noise words already filtered
                            )
                            if not name_found:
                                citation_found = False

                    if citation_found:
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

    # ─── Tier 4: Brave Search API ───────────────────────────────────────

    def _tier4_brave_search(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Verify via Brave Search API."""
        import os
        api_key = os.environ.get("BRAVE_API_KEY")
        if not api_key or self._session is None:
            return None

        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        case_name = p.case_name or case_name_from_metadata(citation.metadata)
        plaintiff = p.plaintiff or str(citation.metadata.get("plaintiff") or "").strip() or None
        defendant = p.defendant or str(citation.metadata.get("defendant") or "").strip() or None

        queries: List[Tuple[str, str]] = []
        if case_name and base:
            queries.append(("brave_name_citation", f'"{case_name}" {base}'))
        if plaintiff and base:
            queries.append(("brave_plaintiff_citation", f'"{plaintiff}" {base}'))
        if defendant and base:
            queries.append(("brave_defendant_citation", f'"{defendant}" {base}'))
        if base:
            queries.append(("brave_citation", f'"{base}" case law'))

        for strategy, query_text in queries:
            brave_url = "https://api.search.brave.com/res/v1/web/search"
            success = False
            error = None
            match_url: Optional[str] = None
            result_count = 0

            try:
                resp = self._session.get(
                    brave_url,
                    params={"q": query_text, "count": 5},
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    timeout=self.request_timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    web_results = data.get("web", {}).get("results", [])
                    result_count = len(web_results)
                    triplet = reporter_triplet(base) if base else None
                    # Only trust results from authoritative legal case sources.
                    # Law review articles, secondary sources, and general commentary
                    # may cite or discuss a reporter/page number without it being
                    # the actual case — filter to primary-source domains.
                    _CASE_DOMAINS = (
                        "courtlistener.com", "scholar.google.com",
                        "justia.com", "casetext.com", "law.justia.com",
                        "law.cornell.edu/supremecourt", "supremecourt.gov",
                        "ca9.uscourts.gov", "ca1.uscourts.gov", "ca2.uscourts.gov",
                        "ca3.uscourts.gov", "ca4.uscourts.gov", "ca5.uscourts.gov",
                        "ca6.uscourts.gov", "ca7.uscourts.gov", "ca8.uscourts.gov",
                        "ca10.uscourts.gov", "ca11.uscourts.gov", "cadc.uscourts.gov",
                        "cafc.uscourts.gov", "leagle.com", "law.resource.org",
                    )
                    for r in web_results:
                        url = r.get("url") or ""
                        if not any(d in url for d in _CASE_DOMAINS):
                            continue
                        snippet = (r.get("description") or "") + " " + (r.get("title") or "")
                        if base and base.lower() in snippet.lower():
                            success = True
                            match_url = url
                            break
                        if triplet:
                            vol, _, page = triplet
                            if vol in snippet and page in snippet:
                                success = True
                                match_url = url
                                break
                else:
                    error = f"HTTP {resp.status_code}"
            except Exception as exc:
                error = str(exc)

            attempts.append(SearchAttempt(
                source="Brave Search",
                strategy=strategy,
                query=query_text,
                success=success,
                result_count=result_count,
                url=match_url or brave_url,
                details="Citation found in Brave Search results" if success else "No match",
                error=error,
            ))
            if success:
                return VerificationDecision(
                    status="Verified (Web Search)",
                    confidence=80,
                    source="Brave Search",
                    source_url=match_url,
                    evidence=f"Brave Search '{strategy}' found a matching citation.",
                    search_attempts=attempts,
                )

        return None

    # ─── Tier 4b: Web Docket Search ─────────────────────────────────────

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

    # ─── Tier 5: Westlaw / Lexis Escalation ─────────────────────────────

    def _tier5_legal_research(
        self,
        citation: ExtractedCitation,
        attempts: List[SearchAttempt],
    ) -> Optional[VerificationDecision]:
        """Escalate to Westlaw KeyCite or Lexis Shepardize as last resort."""
        try:
            from .legal_escalation import escalate_citation
        except ImportError:
            return None

        p = citation.parsed
        base = p.base_citation or strip_pincite(citation.normalized_citation)
        if not base:
            return None

        status, evidence, url, service = escalate_citation(base)

        source_label = "Westlaw (KeyCite)" if service == "westlaw" else "Lexis+ (Shepard's)"

        attempts.append(SearchAttempt(
            source=source_label,
            strategy=f"{service}_escalation",
            query=base,
            success=status in ("verified", "caution"),
            result_count=1 if status not in ("not_found", "error", "skipped") else 0,
            url=url,
            details=evidence,
            error=None if status != "error" else evidence,
        ))

        if status == "skipped":
            return None  # cap reached — fall through to final verdict

        if status == "error":
            return None  # session issue — don't block final verdict

        if status == "not_found":
            return VerificationDecision(
                status="Potential Hallucination",
                confidence=92,
                source=source_label,
                source_url=url,
                evidence=f"{source_label}: {evidence}",
                search_attempts=attempts,
            )

        # negative, caution, or verified — citation exists either way;
        # flag info goes in evidence only, does not affect Verified status
        return VerificationDecision(
            status=f"Verified ({source_label})",
            confidence=95,
            source=source_label,
            source_url=url,
            evidence=evidence,  # already contains flag detail from escalate_citation
            search_attempts=attempts,
        )

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
        headers = {}
        if self._api_token and "courtlistener.com" in url:
            headers["Authorization"] = f"Token {self._api_token}"
        try:
            response = self._session.get(url, params=params, timeout=self.request_timeout, headers=headers or None)
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
    # Allow digits in reporter to handle ordinal editions like "3d", "2d", "4th"
    pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z0-9\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")
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
    overlap_ratio uses Jaccard similarity (intersection / union) to prevent
    a short one-token name from artificially scoring 100% overlap.
    """
    tokens_a = _extract_name_tokens(name_a)
    tokens_b = _extract_name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return (0.0, 0)
    common = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return (len(common) / len(union), len(common))


_PARTY_NOISE_RE = re.compile(
    r"""^(?:
        (?:northern|southern|eastern|western|central)\s+district\s+(?:of\s+)?\w+\s*,?\s* |
        (?:district|superior|supreme|circuit)\s+court\s*,?\s* |
        in\s+(?:re|the\s+matter\s+of)\s+
    )+""",
    re.IGNORECASE | re.VERBOSE,
)


def _clean_party_token(name: str) -> str:
    """Strip court/procedural prefixes that eyecite bleeds into party names."""
    if not name:
        return name
    name = _PARTY_NOISE_RE.sub("", name).strip().rstrip(",").strip()
    # If a comma remains (e.g. "Castellano, No. 4:24-cv-1892"), take just the first token
    if "," in name:
        name = name.split(",")[0].strip()
    return name


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

    # Collect all citation-matching candidates, score by name overlap,
    # return the best match.  Taking the first match is wrong when another
    # case's opinion *cites* the target — we want the case that IS the target.
    citation_matches: List[Tuple[float, Dict[str, Any]]] = []

    for result in candidates:
        if not isinstance(result, dict):
            continue

        result_name = _get_case_name(result)
        result_date = str(result.get("dateFiled") or result.get("date_filed") or "")
        year_ok = (not meta_year) or (meta_year in result_date)

        # Check citation fields
        cite_match = False
        for cite_str in _get_citation_strings(result):
            if _citations_equivalent(cite_str, target_text, target_triplet):
                cite_match = True
                break

        # Check snippet/text fields
        if not cite_match:
            for text_field in ("snippet", "text", "plain_text", "html"):
                text_value = result.get(text_field, "")
                if isinstance(text_value, str) and target_text in text_value:
                    cite_match = True
                    break

        if cite_match:
            # Score by name overlap so the actual case ranks above cases that merely cite it
            name_score = 0.0
            if meta_name and result_name:
                name_score, _ = _name_token_overlap(meta_name, result_name)
            citation_matches.append((name_score, result))
            continue

        # Triplet match against case name fields (weaker — last resort)
        if target_triplet:
            for field_name in ("caseName", "case_name", "caseNameFull"):
                val = str(result.get(field_name, ""))
                if triplet_match(val, target_triplet):
                    citation_matches.append((0.0, result))
                    break

        # Fallback: name/year match (no citation confirmation)
        if meta_name and result_name and year_ok:
            canonical_meta = canonical_text(meta_name)
            canonical_case = canonical_text(result_name)
            if canonical_meta and re.search(
                r"\b" + re.escape(canonical_meta) + r"\b", canonical_case
            ):
                # Don't add to citation_matches — name-only, handled by _best_party_match
                pass

    if not citation_matches:
        return None

    # Sort by name overlap descending; require at least 20% overlap if we have a name
    citation_matches.sort(key=lambda x: x[0], reverse=True)
    best_score, best_result = citation_matches[0]
    if meta_name and best_score < 0.2:
        return None  # citation found but belongs to a completely different case
    return best_result


def _citation_found_wrong_case(
    citation: "ExtractedCitation",
    data: Optional[Dict[str, Any]],
    base_citation: Optional[str] = None,
) -> Optional[str]:
    """Return the actual case name if citation numbers are found in CL but belong
    to a different case than the one named in the brief.

    Returns the actual_case_name string if mismatch detected, else None.
    Used by Tier 1 to short-circuit Brave search when the citation IS real
    but is misattributed to a non-existent case name.
    """
    if data is None:
        return None
    candidates = data.get("results")
    if not isinstance(candidates, list):
        return None

    target_text = base_citation or citation.normalized_citation
    target_triplet = reporter_triplet(target_text)
    meta_name = citation.parsed.case_name or case_name_from_metadata(citation.metadata)
    if not meta_name:
        return None  # no case name in brief → can't detect mismatch

    for result in candidates:
        if not isinstance(result, dict):
            continue
        cite_match = False
        for cite_str in _get_citation_strings(result):
            if _citations_equivalent(cite_str, target_text, target_triplet):
                cite_match = True
                break
        if not cite_match:
            continue
        result_name = _get_case_name(result)
        if not result_name:
            continue
        name_score, _ = _name_token_overlap(meta_name, result_name)
        if name_score < 0.2:
            return result_name  # citation exists but for a different case
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
