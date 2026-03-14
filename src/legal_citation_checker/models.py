"""Data classes for the citation checker pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParagraphSpan:
    """Character offsets for a paragraph within flattened document text."""

    index: int
    text: str
    start: int
    end: int


@dataclass
class DocumentText:
    """Flattened document content plus paragraph offsets."""

    full_text: str
    paragraphs: List[ParagraphSpan]


@dataclass
class SearchAttempt:
    """One verification attempt against a source/strategy."""

    source: str
    strategy: str
    query: str
    success: bool
    result_count: int = 0
    url: Optional[str] = None
    details: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationDecision:
    """Outcome of citation verification."""

    status: str
    confidence: int
    source: Optional[str] = None
    source_url: Optional[str] = None
    evidence: str = ""
    search_attempts: List[SearchAttempt] = field(default_factory=list)

    def clone(self) -> "VerificationDecision":
        return VerificationDecision(
            status=self.status,
            confidence=self.confidence,
            source=self.source,
            source_url=self.source_url,
            evidence=self.evidence,
            search_attempts=[SearchAttempt(**attempt.to_dict()) for attempt in self.search_attempts],
        )


@dataclass
class CitationAudit:
    """Per-citation audit details for report output."""

    index: int
    raw_citation: str
    normalized_citation: str
    citation_type: str
    context: str
    paragraph_index: Optional[int]
    metadata: Dict[str, Any]
    bluebook_normalized: bool
    status: str
    confidence: int
    source: Optional[str]
    source_url: Optional[str]
    evidence: str
    search_attempts: List[SearchAttempt] = field(default_factory=list)
    bluebook_citation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["search_attempts"] = [attempt.to_dict() for attempt in self.search_attempts]
        return data


@dataclass
class ParsedCitation:
    """Structured citation components parsed once during extraction.

    Holds the volume/reporter/page triplet, party names, court, and year
    so downstream code never has to re-parse from strings.
    """

    volume: Optional[str] = None
    reporter: Optional[str] = None
    page: Optional[str] = None
    plaintiff: Optional[str] = None
    defendant: Optional[str] = None
    year: Optional[str] = None
    court: Optional[str] = None
    pincite: Optional[str] = None
    reporter_full_name: Optional[str] = None
    cite_type: Optional[str] = None  # e.g. "federal", "state", "specialty"

    @property
    def case_name(self) -> str:
        """Build 'Plaintiff v. Defendant' if both parties are known."""
        if self.plaintiff and self.defendant:
            return f"{self.plaintiff} v. {self.defendant}"
        return ""

    @property
    def base_citation(self) -> str:
        """Volume Reporter Page without pincite, e.g. '347 U.S. 483'."""
        if self.volume and self.reporter and self.page:
            return f"{self.volume} {self.reporter} {self.page}"
        return ""

    @property
    def has_triplet(self) -> bool:
        return bool(self.volume and self.reporter and self.page)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ExtractedCitation:
    """Intermediate citation object before verification."""

    index: int
    raw_citation: str
    normalized_citation: str
    citation_type: str
    context: str
    paragraph_index: Optional[int]
    metadata: Dict[str, Any]
    bluebook_normalized: bool
    parsed: ParsedCitation = field(default_factory=ParsedCitation)
