"""Bluebook citation formatter.

Formats structured citations into proper Bluebook 21st Edition style using
data from reporters-db (case name abbreviations, state abbreviations) and
courts-db (court citation strings).

Bluebook case citation format (Rule 10):
    {Case Name Abbreviated}, {Volume} {Reporter} {Page} ({Court} {Year}).

Examples:
    Brown v. Bd. of Educ., 347 U.S. 483 (1954).
    Riley v. California, 573 U.S. 373 (2014).
    Carpenter v. United States, 585 U.S. 296 (2018).
    Thompson v. Dig. Analytics Corp., 847 F.3d 1203 (9th Cir. 2021).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .models import ParsedCitation


class BluebookFormatter:
    """Formats ParsedCitation into Bluebook style."""

    def __init__(self) -> None:
        self._case_name_abbrevs: Optional[Dict[str, str]] = None
        self._state_abbrevs: Optional[Dict[str, str]] = None
        self._court_strings: Optional[Dict[str, str]] = None

    def format(self, parsed: ParsedCitation) -> str:
        """Format a parsed citation in Bluebook style.

        Returns the formatted citation string, or empty string if
        insufficient data.
        """
        if not parsed.has_triplet:
            return ""

        parts: List[str] = []

        # Case name (abbreviated)
        case_name = self.abbreviate_case_name(parsed.case_name)
        if case_name:
            parts.append(f"{case_name},")

        # Volume Reporter Page
        parts.append(f"{parsed.volume} {parsed.reporter} {parsed.page}")

        # Pincite
        if parsed.pincite:
            parts.append(f", {parsed.pincite}")

        # Parenthetical: (Court Year)
        court_year = self._format_court_year(parsed)
        if court_year:
            parts.append(f" ({court_year})")

        return " ".join(parts).replace(" ,", ",").replace("  ", " ").rstrip(",") + "."

    def abbreviate_case_name(self, case_name: str) -> str:
        """Abbreviate a case name per Bluebook Table T6 rules.

        Bluebook rules for case names (Rule 10.2.1):
        - Abbreviate words listed in Table T6 (CASE_NAME_ABBREVIATIONS)
        - Keep first word of each party's name unabbreviated unless it's
          a commonly abbreviated word
        - Omit "The" at the start
        - Keep "v." between parties
        """
        if not case_name:
            return ""

        abbrevs = self._load_case_name_abbreviations()
        if not abbrevs:
            return case_name

        # Split on "v." to handle each party separately
        if " v. " in case_name:
            parties = case_name.split(" v. ", 1)
            abbreviated_parties = [
                self._abbreviate_party_name(p.strip(), abbrevs)
                for p in parties
            ]
            return " v. ".join(abbreviated_parties)

        return self._abbreviate_party_name(case_name, abbrevs)

    def abbreviate_state(self, state_name: str) -> str:
        """Abbreviate a state name per Bluebook Table T6."""
        abbrevs = self._load_state_abbreviations()
        return abbrevs.get(state_name, state_name)

    def court_citation_string(self, court_id: str) -> str:
        """Get the Bluebook citation string for a court ID.

        Maps eyecite codes like 'ca9' -> '9th Cir.',
        'scotus' -> '' (omitted for SCOTUS in U.S. Reports).
        """
        strings = self._load_court_strings()
        return strings.get(court_id, court_id)

    def format_full(
        self,
        parsed: ParsedCitation,
        include_pincite: bool = True,
    ) -> str:
        """Format with all available information, including pincite."""
        if not parsed.has_triplet:
            return ""

        case_name = self.abbreviate_case_name(parsed.case_name)
        reporter_part = f"{parsed.volume} {parsed.reporter} {parsed.page}"

        if include_pincite and parsed.pincite:
            reporter_part += f", {parsed.pincite}"

        court_year = self._format_court_year(parsed)
        paren = f" ({court_year})" if court_year else ""

        if case_name:
            return f"{case_name}, {reporter_part}{paren}."
        return f"{reporter_part}{paren}."

    def format_short(self, parsed: ParsedCitation) -> str:
        """Format a short-form citation (for subsequent references).

        Bluebook Rule 10.9: short form uses one party name + volume/page.
        Example: Brown, 347 U.S. at 495.
        """
        if not parsed.has_triplet:
            return ""

        # Use plaintiff or first party for short form
        short_name = ""
        if parsed.plaintiff:
            short_name = parsed.plaintiff
        elif parsed.defendant:
            short_name = parsed.defendant

        if short_name and parsed.pincite:
            return f"{short_name}, {parsed.volume} {parsed.reporter} at {parsed.pincite}."
        elif short_name:
            return f"{short_name}, {parsed.volume} {parsed.reporter} {parsed.page}."
        elif parsed.pincite:
            return f"{parsed.volume} {parsed.reporter} at {parsed.pincite}."
        return f"{parsed.volume} {parsed.reporter} {parsed.page}."

    # ─── Private helpers ────────────────────────────────────────────────

    def _abbreviate_party_name(
        self,
        party: str,
        abbrevs: Dict[str, str],
    ) -> str:
        """Abbreviate a single party's name.

        Bluebook Rule 10.2.1(c): abbreviate words in Table T6 that are
        not the first word of a party name, UNLESS the first word itself
        is an entity word that should always be abbreviated.
        """
        # Strip leading "The"
        if party.lower().startswith("the "):
            party = party[4:]

        words = party.split()
        if not words:
            return party

        result: List[str] = []
        # Words that should always be abbreviated even as first word
        _ALWAYS_ABBREVIATE = frozenset({
            "association", "board", "commission", "committee", "company",
            "corporation", "department", "government", "incorporated",
            "international", "national", "organization", "railway",
            "transportation", "university",
        })

        for i, word in enumerate(words):
            # Strip trailing punctuation for lookup
            clean = word.rstrip(".,;:")
            trailing = word[len(clean):]

            lookup = clean.lower()
            abbrev = abbrevs.get(lookup)

            if abbrev:
                # First word: only abbreviate if it's an entity word
                if i == 0 and lookup not in _ALWAYS_ABBREVIATE:
                    result.append(word)
                else:
                    # Preserve trailing punctuation
                    result.append(abbrev + trailing)
            else:
                result.append(word)

        return " ".join(result)

    def _format_court_year(self, parsed: ParsedCitation) -> str:
        """Build the (Court Year) parenthetical.

        Bluebook Rule 10.4:
        - Omit court when citation is to the court's official reporter
          (e.g., U.S. Reports -> no court needed for SCOTUS)
        - Include court abbreviation for all others
        """
        court_str = ""
        if parsed.court:
            court_str = self.court_citation_string(parsed.court)
            # SCOTUS citations in U.S. Reports omit the court
            if parsed.court == "scotus" and parsed.reporter in ("U.S.",):
                court_str = ""

        parts = [p for p in [court_str, parsed.year or ""] if p]
        return " ".join(parts)

    def _load_case_name_abbreviations(self) -> Dict[str, str]:
        """Load reverse mapping: full word (lowercase) -> abbreviation."""
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
                # Map lowercase full word -> abbreviation
                abbrevs[word.lower()] = abbrev

        self._case_name_abbrevs = abbrevs
        return abbrevs

    def _load_state_abbreviations(self) -> Dict[str, str]:
        """Load state name -> Bluebook abbreviation mapping."""
        if self._state_abbrevs is not None:
            return self._state_abbrevs

        abbrevs: Dict[str, str] = {}
        try:
            from reporters_db import STATE_ABBREVIATIONS  # type: ignore
        except ImportError:
            self._state_abbrevs = abbrevs
            return abbrevs

        # STATE_ABBREVIATIONS is abbreviation -> full name
        # We want full name -> abbreviation
        for abbrev, full_name in STATE_ABBREVIATIONS.items():
            abbrevs[full_name] = abbrev

        self._state_abbrevs = abbrevs
        return abbrevs

    def _load_court_strings(self) -> Dict[str, str]:
        """Load court ID -> Bluebook citation string mapping."""
        if self._court_strings is not None:
            return self._court_strings

        strings: Dict[str, str] = {}
        try:
            from courts_db import courts as _courts_list  # type: ignore
        except ImportError:
            # Fallback: common court mappings
            strings = {
                "scotus": "",
                "ca1": "1st Cir.",
                "ca2": "2d Cir.",
                "ca3": "3d Cir.",
                "ca4": "4th Cir.",
                "ca5": "5th Cir.",
                "ca6": "6th Cir.",
                "ca7": "7th Cir.",
                "ca8": "8th Cir.",
                "ca9": "9th Cir.",
                "ca10": "10th Cir.",
                "ca11": "11th Cir.",
                "cadc": "D.C. Cir.",
                "cafc": "Fed. Cir.",
            }
            self._court_strings = strings
            return strings

        for court in _courts_list:
            if isinstance(court, dict):
                court_id = court.get("id", "")
                cite_str = court.get("citation_string", "")
                if court_id and cite_str:
                    strings[court_id] = cite_str

        # SCOTUS in U.S. Reports doesn't need court string
        if "scotus" in strings:
            strings["scotus"] = ""

        self._court_strings = strings
        return strings
