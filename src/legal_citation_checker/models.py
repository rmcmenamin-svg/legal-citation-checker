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

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["search_attempts"] = [attempt.to_dict() for attempt in self.search_attempts]
        return data


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
