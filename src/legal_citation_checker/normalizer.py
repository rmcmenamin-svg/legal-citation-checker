"""Bluebook citation normalization and reporter alias management."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


class CitationNormalizer:
    """Normalizes citations to Bluebook format using reporters-db."""

    def __init__(self) -> None:
        self._reporter_aliases: Optional[Dict[str, str]] = None

    def normalize(self, citation_text: str, metadata: Dict[str, Any]) -> Tuple[str, bool]:
        """Normalize a citation string to Bluebook format.

        Returns a tuple of (normalized_text, was_changed).
        """
        original = citation_text or ""
        normalized = original

        normalized = normalized.replace("\u00a0", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Normalize section symbols and spacing.
        normalized = re.sub(r"\b[Ss]ection\s+", "§ ", normalized)
        normalized = re.sub(r"§\s*", "§ ", normalized)

        # Canonicalize the common case-name separator.
        normalized = re.sub(r"\sv(?!\.)\s", " v. ", normalized)

        # Normalize punctuation spacing.
        normalized = re.sub(r"\s*,\s*", ", ", normalized)
        normalized = re.sub(r"\s*\(\s*", " (", normalized)
        normalized = re.sub(r"\s*\)\s*", ") ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Reporter abbreviation cleanup when reporters-db is available.
        normalized = self._normalize_reporter_abbreviation(normalized)

        # Optional external Bluebook formatter if present in environment.
        normalized = self._apply_external_bluebook_formatter(normalized)

        # Ensure trailing spaces/punctuation are standardized.
        normalized = normalized.rstrip(" ;")

        if not normalized:
            normalized = original

        changed = normalized != original
        metadata["bluebook_normalized"] = changed
        return normalized, changed

    def _normalize_reporter_abbreviation(self, citation: str) -> str:
        aliases = self._load_reporter_aliases()
        if not aliases:
            return citation

        pattern = re.compile(r"\b(\d{1,4})\s+([A-Za-z][A-Za-z\s\.]{0,40}[A-Za-z\.])\s+(\d{1,5})\b")

        def replace(match: re.Match[str]) -> str:
            volume = match.group(1)
            reporter = match.group(2).strip()
            page = match.group(3)
            key = canonical_text(reporter)
            canonical = aliases.get(key)
            if not canonical:
                return match.group(0)
            return f"{volume} {canonical} {page}"

        return pattern.sub(replace, citation)

    def _load_reporter_aliases(self) -> Dict[str, str]:
        if self._reporter_aliases is not None:
            return self._reporter_aliases

        aliases: Dict[str, str] = {}
        try:
            from reporters_db import REPORTERS  # type: ignore
        except Exception:
            self._reporter_aliases = aliases
            return aliases

        if isinstance(REPORTERS, dict):
            for canonical, entries in REPORTERS.items():
                if not isinstance(canonical, str):
                    continue
                canonical_key = canonical_text(canonical)
                aliases[canonical_key] = canonical

                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        name = entry.get("name")
                        if isinstance(name, str):
                            aliases[canonical_text(name)] = canonical
                        variations = entry.get("variations")
                        if isinstance(variations, dict):
                            for value in variations.values():
                                if isinstance(value, list):
                                    for item in value:
                                        if isinstance(item, str):
                                            aliases[canonical_text(item)] = canonical
                                elif isinstance(value, str):
                                    aliases[canonical_text(value)] = canonical

        self._reporter_aliases = aliases
        return aliases

    def _apply_external_bluebook_formatter(self, citation: str) -> str:
        module_candidates = [
            "bluebook_cite",
            "bluebookcite",
        ]
        function_candidates = [
            "format_citation",
            "format",
            "normalize_citation",
        ]

        for module_name in module_candidates:
            try:
                module = __import__(module_name)
            except Exception:
                continue

            for fn_name in function_candidates:
                fn = getattr(module, fn_name, None)
                if not callable(fn):
                    continue
                try:
                    result = fn(citation)
                except Exception:
                    continue
                if isinstance(result, str) and result.strip():
                    return result.strip()

        return citation


def canonical_text(value: str) -> str:
    """Lowercase and strip punctuation for comparison."""
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()
