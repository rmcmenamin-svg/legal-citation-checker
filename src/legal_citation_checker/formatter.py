"""Legal citation formatter supporting Bluebook and California Style Manual.

Formats structured citations using data from reporters-db (case name
abbreviations, state abbreviations) and courts-db (court citation strings).

Bluebook case citation format (Rule 10):
    {Case Name Abbreviated}, {Volume} {Reporter} {Page} ({Court} {Year}).
    Example: Brown v. Bd. of Educ., 347 U.S. 483 (1954).

California Style Manual format (§ 1:1):
    {Case Name} ({Year}) {Volume} {Reporter} {Page}.
    Example: People v. Prettyman (1996) 14 Cal.4th 248.

Key CSM differences:
    - Year parenthetical comes after case name, before reporter
    - No spaces within reporter abbreviations (Cal.4th not Cal. 4th)
    - No case name abbreviation
    - Court of Appeal district noted in parenthetical
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .models import ParsedCitation

# California state court IDs from courts-db.
_CA_STATE_COURT_IDS = frozenset({
    "cal",             # California Supreme Court
    "calctapp",        # California Courts of Appeal (generic)
    "calctapp1d",      # First Appellate District
    "calctapp2d",      # Second Appellate District
    "calctapp3d",      # Third Appellate District
    "calctapp4d",      # Fourth Appellate District
    "calctapp5d",      # Fifth Appellate District
    "calctapp6d",      # Sixth Appellate District
    "calsuperct",      # California Superior Court
    "calappdeptsuper", # California Superior Court, Appellate Division
    "caldistct",       # California District Court (historical)
    "calag",           # California Attorney General
    "caljp",           # Commission on Judicial Performance
})

# California reporter abbreviations (official reporters for CSM).
_CA_REPORTERS = frozenset({
    "Cal.", "Cal. 2d", "Cal. 3d", "Cal. 4th", "Cal. 5th",
    "Cal. App.", "Cal. App. 2d", "Cal. App. 3d", "Cal. App. 4th", "Cal. App. 5th",
    "Cal. App. Supp.", "Cal. App. Supp. 2d",
    "Cal. Rptr.", "Cal. Rptr. 2d", "Cal. Rptr. 3d",
    "Cal. Comp. Cases",
})


def is_california_case(parsed: ParsedCitation) -> bool:
    """Determine if a citation is a California state case."""
    if parsed.court and parsed.court in _CA_STATE_COURT_IDS:
        return True
    if parsed.reporter and parsed.reporter in _CA_REPORTERS:
        return True
    if parsed.cite_type == "state" and parsed.reporter:
        reporter_lower = parsed.reporter.lower()
        if "cal" in reporter_lower:
            return True
    return False


class CitationFormatter:
    """Formats citations in Bluebook or California Style Manual format.

    Automatically detects California state cases and uses CSM format.
    All other cases use Bluebook format.
    """

    def __init__(self, style: str = "auto") -> None:
        """Initialize formatter.

        Args:
            style: "auto" (detect per-citation), "bluebook", or "csm"
                   (California Style Manual).
        """
        self.style = style.lower()
        self._case_name_abbrevs: Optional[Dict[str, str]] = None
        self._state_abbrevs: Optional[Dict[str, str]] = None
        self._court_strings: Optional[Dict[str, str]] = None

    def format(self, parsed: ParsedCitation) -> str:
        """Format a citation in the appropriate style.

        In "auto" mode, California state cases use CSM format,
        everything else uses Bluebook.
        """
        if not parsed.has_triplet:
            return ""

        if self._use_csm(parsed):
            return self._format_csm(parsed)
        return self._format_bluebook(parsed)

    def format_full(
        self,
        parsed: ParsedCitation,
        include_pincite: bool = True,
    ) -> str:
        """Format with all available information."""
        if not parsed.has_triplet:
            return ""
        if self._use_csm(parsed):
            return self._format_csm(parsed, include_pincite=include_pincite)
        return self._format_bluebook_full(parsed, include_pincite=include_pincite)

    def format_short(self, parsed: ParsedCitation) -> str:
        """Short-form citation for subsequent references."""
        if not parsed.has_triplet:
            return ""
        if self._use_csm(parsed):
            return self._format_csm_short(parsed)
        return self._format_bluebook_short(parsed)

    # ─── Bluebook formatting ───────────────────────────────────────────

    def _format_bluebook(self, parsed: ParsedCitation) -> str:
        case_name = self.abbreviate_case_name(parsed.case_name)
        reporter_part = f"{parsed.volume} {parsed.reporter} {parsed.page}"
        if parsed.pincite:
            reporter_part += f", {parsed.pincite}"
        court_year = self._bluebook_court_year(parsed)
        paren = f" ({court_year})" if court_year else ""

        if case_name:
            return f"{case_name}, {reporter_part}{paren}."
        return f"{reporter_part}{paren}."

    def _format_bluebook_full(
        self, parsed: ParsedCitation, include_pincite: bool = True,
    ) -> str:
        case_name = self.abbreviate_case_name(parsed.case_name)
        reporter_part = f"{parsed.volume} {parsed.reporter} {parsed.page}"
        if include_pincite and parsed.pincite:
            reporter_part += f", {parsed.pincite}"
        court_year = self._bluebook_court_year(parsed)
        paren = f" ({court_year})" if court_year else ""
        if case_name:
            return f"{case_name}, {reporter_part}{paren}."
        return f"{reporter_part}{paren}."

    def _format_bluebook_short(self, parsed: ParsedCitation) -> str:
        short_name = parsed.plaintiff or parsed.defendant or ""
        if short_name and parsed.pincite:
            return f"{short_name}, {parsed.volume} {parsed.reporter} at {parsed.pincite}."
        elif short_name:
            return f"{short_name}, {parsed.volume} {parsed.reporter} {parsed.page}."
        elif parsed.pincite:
            return f"{parsed.volume} {parsed.reporter} at {parsed.pincite}."
        return f"{parsed.volume} {parsed.reporter} {parsed.page}."

    def _bluebook_court_year(self, parsed: ParsedCitation) -> str:
        court_str = ""
        if parsed.court:
            court_str = self.court_citation_string(parsed.court)
            if parsed.court == "scotus" and parsed.reporter in ("U.S.",):
                court_str = ""
        parts = [p for p in [court_str, parsed.year or ""] if p]
        return " ".join(parts)

    # ─── California Style Manual formatting ────────────────────────────

    def _format_csm(
        self, parsed: ParsedCitation, include_pincite: bool = True,
    ) -> str:
        """Format per California Style Manual.

        CSM format: Case Name (Year) Volume Reporter Page[, Pincite].
        Reporter has no internal spaces: Cal.4th not Cal. 4th.
        """
        case_name = parsed.case_name  # CSM does NOT abbreviate case names
        year_paren = f" ({parsed.year})" if parsed.year else ""
        reporter_csm = self._csm_reporter(parsed.reporter or "")
        cite_part = f"{parsed.volume} {reporter_csm} {parsed.page}"
        if include_pincite and parsed.pincite:
            cite_part += f", {parsed.pincite}"

        # For Court of Appeal, add district info
        district = self._csm_district(parsed.court)

        if case_name and district:
            return f"{case_name}{year_paren} {cite_part} [{district}]."
        elif case_name:
            return f"{case_name}{year_paren} {cite_part}."
        elif district:
            return f"{year_paren.strip()} {cite_part} [{district}].".strip()
        return f"{cite_part}."

    def _format_csm_short(self, parsed: ParsedCitation) -> str:
        """CSM short form: Case Name, supra, Volume Reporter at Page."""
        short_name = parsed.plaintiff or parsed.defendant or ""
        reporter_csm = self._csm_reporter(parsed.reporter or "")
        if short_name and parsed.pincite:
            return f"{short_name}, supra, {parsed.volume} {reporter_csm} at p. {parsed.pincite}."
        elif short_name:
            return f"{short_name}, supra, {parsed.volume} {reporter_csm} {parsed.page}."
        elif parsed.pincite:
            return f"{parsed.volume} {reporter_csm} at p. {parsed.pincite}."
        return f"{parsed.volume} {reporter_csm} {parsed.page}."

    def _csm_reporter(self, reporter: str) -> str:
        """Convert Bluebook-spaced reporter to CSM no-space format.

        CSM: Cal.4th, Cal.App.5th, F.Supp.2d (no spaces in reporter).
        """
        if not reporter:
            return reporter
        # Remove spaces between abbreviation parts
        # "Cal. App. 5th" -> "Cal.App.5th"
        # "F. Supp. 3d" -> "F.Supp.3d"
        # But preserve "U.S." as-is (not a California reporter)
        parts = reporter.split()
        if len(parts) <= 1:
            return reporter
        return "".join(parts)

    def _csm_district(self, court: Optional[str]) -> str:
        """Get the CSM appellate district string, if applicable."""
        if not court:
            return ""
        _DISTRICT_MAP = {
            "calctapp1d": "1st Dist.",
            "calctapp2d": "2d Dist.",
            "calctapp3d": "3d Dist.",
            "calctapp4d": "4th Dist.",
            "calctapp5d": "5th Dist.",
            "calctapp6d": "6th Dist.",
        }
        return _DISTRICT_MAP.get(court, "")

    # ─── Style detection ───────────────────────────────────────────────

    def _use_csm(self, parsed: ParsedCitation) -> bool:
        if self.style == "csm":
            return True
        if self.style == "bluebook":
            return False
        # Auto-detect: use CSM for California state cases
        return is_california_case(parsed)

    # ─── Shared helpers ────────────────────────────────────────────────

    def abbreviate_case_name(self, case_name: str) -> str:
        """Abbreviate per Bluebook Table T6. CSM does not abbreviate."""
        if not case_name:
            return ""
        abbrevs = self._load_case_name_abbreviations()
        if not abbrevs:
            return case_name
        if " v. " in case_name:
            parties = case_name.split(" v. ", 1)
            return " v. ".join(
                self._abbreviate_party_name(p.strip(), abbrevs) for p in parties
            )
        return self._abbreviate_party_name(case_name, abbrevs)

    def abbreviate_state(self, state_name: str) -> str:
        abbrevs = self._load_state_abbreviations()
        return abbrevs.get(state_name, state_name)

    def court_citation_string(self, court_id: str) -> str:
        strings = self._load_court_strings()
        return strings.get(court_id, court_id)

    def _abbreviate_party_name(
        self, party: str, abbrevs: Dict[str, str],
    ) -> str:
        if party.lower().startswith("the "):
            party = party[4:]
        words = party.split()
        if not words:
            return party

        _ALWAYS_ABBREVIATE = frozenset({
            "association", "board", "commission", "committee", "company",
            "corporation", "department", "government", "incorporated",
            "international", "national", "organization", "railway",
            "transportation", "university",
        })
        result: List[str] = []
        for i, word in enumerate(words):
            clean = word.rstrip(".,;:")
            trailing = word[len(clean):]
            lookup = clean.lower()
            abbrev = abbrevs.get(lookup)
            if abbrev:
                if i == 0 and lookup not in _ALWAYS_ABBREVIATE:
                    result.append(word)
                else:
                    result.append(abbrev + trailing)
            else:
                result.append(word)
        return " ".join(result)

    # ─── Data loading ──────────────────────────────────────────────────

    def _load_case_name_abbreviations(self) -> Dict[str, str]:
        if self._case_name_abbrevs is not None:
            return self._case_name_abbrevs
        abbrevs: Dict[str, str] = {}
        try:
            from reporters_db import CASE_NAME_ABBREVIATIONS  # type: ignore
        except ImportError:
            self._case_name_abbrevs = abbrevs
            return abbrevs
        for abbrev, words in CASE_NAME_ABBREVIATIONS.items():
            for word in words:
                abbrevs[word.lower()] = abbrev
        self._case_name_abbrevs = abbrevs
        return abbrevs

    def _load_state_abbreviations(self) -> Dict[str, str]:
        if self._state_abbrevs is not None:
            return self._state_abbrevs
        abbrevs: Dict[str, str] = {}
        try:
            from reporters_db import STATE_ABBREVIATIONS  # type: ignore
        except ImportError:
            self._state_abbrevs = abbrevs
            return abbrevs
        for abbrev, full_name in STATE_ABBREVIATIONS.items():
            abbrevs[full_name] = abbrev
        self._state_abbrevs = abbrevs
        return abbrevs

    def _load_court_strings(self) -> Dict[str, str]:
        if self._court_strings is not None:
            return self._court_strings
        strings: Dict[str, str] = {}
        try:
            from courts_db import courts as _courts_list  # type: ignore
        except ImportError:
            strings = {
                "scotus": "",
                "ca1": "1st Cir.", "ca2": "2d Cir.", "ca3": "3d Cir.",
                "ca4": "4th Cir.", "ca5": "5th Cir.", "ca6": "6th Cir.",
                "ca7": "7th Cir.", "ca8": "8th Cir.", "ca9": "9th Cir.",
                "ca10": "10th Cir.", "ca11": "11th Cir.",
                "cadc": "D.C. Cir.", "cafc": "Fed. Cir.",
            }
            self._court_strings = strings
            return strings
        for court in _courts_list:
            if isinstance(court, dict):
                court_id = court.get("id", "")
                cite_str = court.get("citation_string", "")
                if court_id and cite_str:
                    strings[court_id] = cite_str
        if "scotus" in strings:
            strings["scotus"] = ""
        self._court_strings = strings
        return strings


# ── Backward compatibility ──────────────────────────────────────────────

# Old name still works
BluebookFormatter = CitationFormatter
