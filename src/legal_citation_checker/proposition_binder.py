"""Proposition-level quote-citation binding engine.

Replaces naive proximity-based quote assignment with a structured approach:

1. Segment text into propositions (sentence/clause level)
2. Identify quotes and citations within each proposition
3. Bind quotes to citations using tiered confidence rules
4. Flag "floating quotes" (quotes with no valid citation match)

Binding tiers (highest to lowest confidence):
  Tier 1 (0.95): Quote contains citation OR citation inside quote's sentence
  Tier 2 (0.90): Quote and citation in same sentence
  Tier 3 (0.75): Quote precedes citation within same paragraph, no competing cite
  Tier 4 (0.50): Quote and citation in same paragraph, multiple competing cites

Anything below threshold (default 0.7) is NOT assigned — flagged as ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Sentence segmentation ──────────────────────────────────────────────
# Legal text has tricky abbreviations that look like sentence endings.

_LEGAL_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "jr", "sr", "st", "inc", "ltd", "llc",
    "corp", "co", "no", "nos", "vol", "rev", "stat", "gen",
    "app", "supp", "cir", "dist", "ct", "dept", "gov",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "v", "vs",  # case names
    "u", "s",  # "U.S."
    "f", "e", "n", "w",  # compass / reporter abbreviations
    "ed", "ex", "exh", "pl", "def", "aff",
    "compl", "decl", "dep", "tr", "dkt", "ecf",
})

# Sentence boundary: period/question/exclamation followed by space + uppercase
# But NOT after known abbreviations.
_SENTENCE_END_RE = re.compile(
    r'([.!?])"?\s+(?=[A-Z"\u201c])',
)

# Quote extraction (double quotes / smart quotes)
_QUOTE_RE = re.compile(
    r'["\u201c](.+?)["\u201d]',
    re.DOTALL,
)

# Paragraph split
_PARA_SPLIT_RE = re.compile(r'\n\s*\n')


@dataclass
class TextSpan:
    """A span of text with character offsets."""
    text: str
    start: int  # offset in the full document text
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Quote:
    """A quoted passage within the document."""
    text: str
    start: int
    end: int
    sentence_index: Optional[int] = None
    paragraph_index: Optional[int] = None


@dataclass
class CitationSpan:
    """A citation's location within the document."""
    raw_text: str
    start: int
    end: int
    sentence_index: Optional[int] = None
    paragraph_index: Optional[int] = None


@dataclass
class QuoteBinding:
    """A binding between a quote and a citation."""
    quote: Quote
    citation_start: int  # character offset of bound citation
    confidence: float    # 0.0 - 1.0
    tier: int            # 1-4
    reason: str


@dataclass
class Proposition:
    """A proposition unit: a sentence or clause with its quotes and citations."""
    text: str
    start: int
    end: int
    sentence_index: int
    paragraph_index: int
    quotes: List[Quote] = field(default_factory=list)
    citations: List[CitationSpan] = field(default_factory=list)


def _is_abbreviation(text: str, period_pos: int) -> bool:
    """Check if a period at position `period_pos` is part of an abbreviation."""
    # Check for closing parenthesis before period: "(1954)." is a sentence end
    if period_pos >= 1 and text[period_pos - 1] == ")":
        paren_start = text.rfind("(", max(0, period_pos - 10), period_pos)
        if paren_start >= 0:
            inside = text[paren_start + 1:period_pos - 1].strip()
            # Year like (1954), (2024) — this IS a sentence boundary
            if inside.isdigit() and len(inside) == 4:
                return False
            # Court abbreviation like (3d Cir.) — this IS a sentence boundary
            if any(c.isalpha() for c in inside):
                return False

    # Walk backwards past any closing punctuation (parentheses, quotes)
    i = period_pos - 1
    while i >= 0 and text[i] in ")]\u201d\"'":
        i -= 1

    # Now walk backwards to find the word
    word_end = i + 1
    while i >= 0 and text[i].isalpha():
        i -= 1
    word = text[i + 1:word_end].lower()

    if word in _LEGAL_ABBREVIATIONS:
        return True
    # Single letter followed by period (initials like "U.S.C.")
    if len(word) <= 1 and word.isalpha():
        return True
    # Empty word (e.g. after closing parenthesis with no alpha before it)
    if not word:
        return False
    # Check for patterns like "F.3d", "F.Supp."
    if period_pos + 1 < len(text) and text[period_pos + 1].isdigit():
        return True
    return False


def segment_sentences(text: str, base_offset: int = 0) -> List[TextSpan]:
    """Split text into sentences, respecting legal abbreviations.

    Returns list of TextSpan with offsets relative to document start.
    """
    if not text.strip():
        return []

    sentences: List[TextSpan] = []
    last_end = 0

    for match in _SENTENCE_END_RE.finditer(text):
        period_pos = match.start()

        # Skip if this period is part of an abbreviation
        if _is_abbreviation(text, period_pos):
            continue

        # Include the sentence-ending punctuation
        sent_end = match.start() + 1  # include the period/!/?"
        sent_text = text[last_end:sent_end].strip()
        if sent_text:
            sentences.append(TextSpan(
                text=sent_text,
                start=base_offset + last_end,
                end=base_offset + sent_end,
            ))
        last_end = match.end()

    # Remainder
    remainder = text[last_end:].strip()
    if remainder:
        sentences.append(TextSpan(
            text=remainder,
            start=base_offset + last_end,
            end=base_offset + len(text),
        ))

    return sentences


def segment_paragraphs(text: str) -> List[TextSpan]:
    """Split text into paragraphs."""
    paragraphs: List[TextSpan] = []
    for match in _PARA_SPLIT_RE.finditer(text):
        pass  # just to find split points

    parts = _PARA_SPLIT_RE.split(text)
    offset = 0
    for part in parts:
        stripped = part.strip()
        if stripped:
            start = text.index(part, offset) if part in text[offset:] else offset
            paragraphs.append(TextSpan(
                text=stripped,
                start=start,
                end=start + len(part),
            ))
        offset += len(part) + 2  # account for \n\n

    return paragraphs


def extract_quotes(text: str, base_offset: int = 0) -> List[Quote]:
    """Extract all quoted passages from text."""
    quotes = []
    for match in _QUOTE_RE.finditer(text):
        quote_text = match.group(1).strip()
        # Only include substantive quotes (not single words)
        if len(quote_text) > 10:
            quotes.append(Quote(
                text=quote_text,
                start=base_offset + match.start(),
                end=base_offset + match.end(),
            ))
    return quotes


def _spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two spans overlap."""
    return not (a_end <= b_start or b_end <= a_start)


def _span_contains(outer_start: int, outer_end: int, inner_start: int, inner_end: int) -> bool:
    """Check if outer span contains inner span."""
    return outer_start <= inner_start and inner_end <= outer_end


class PropositionBinder:
    """Bind quotes to citations at the proposition level.

    Usage:
        binder = PropositionBinder(full_text)
        binder.register_citation(start=100, end=120, raw_text="Smith Dep. 42:20")
        binder.register_citation(start=500, end=520, raw_text="Ex. A at 3")
        bindings = binder.bind()
        floating = binder.floating_quotes()
    """

    def __init__(self, full_text: str, binding_threshold: float = 0.70):
        self.full_text = full_text
        self.binding_threshold = binding_threshold

        # Parse structure
        self.paragraphs = segment_paragraphs(full_text)
        self.sentences: List[TextSpan] = []
        self._para_for_sentence: Dict[int, int] = {}  # sentence_idx -> para_idx

        for para_idx, para in enumerate(self.paragraphs):
            para_sentences = segment_sentences(para.text, base_offset=para.start)
            for sent in para_sentences:
                sent_idx = len(self.sentences)
                self._para_for_sentence[sent_idx] = para_idx
                self.sentences.append(sent)

        # Extract quotes and assign to sentences/paragraphs
        self.quotes = extract_quotes(full_text)
        for q in self.quotes:
            q.sentence_index = self._find_sentence(q.start)
            q.paragraph_index = self._find_paragraph(q.start)

        # Citations registered by caller
        self._citations: List[CitationSpan] = []
        self._bindings: Optional[List[QuoteBinding]] = None

    def register_citation(self, start: int, end: int, raw_text: str) -> None:
        """Register a citation's location for binding."""
        cite = CitationSpan(
            raw_text=raw_text,
            start=start,
            end=end,
            sentence_index=self._find_sentence(start),
            paragraph_index=self._find_paragraph(start),
        )
        self._citations.append(cite)
        self._bindings = None  # invalidate cache

    def bind(self) -> List[QuoteBinding]:
        """Compute all quote-citation bindings.

        Returns bindings sorted by confidence (highest first).
        """
        if self._bindings is not None:
            return self._bindings

        bindings: List[QuoteBinding] = []
        bound_quotes: set = set()  # quote indices already bound

        # Sort citations by position for forward-preference
        sorted_cites = sorted(self._citations, key=lambda c: c.start)

        # Tier 1: Quote contains citation or citation in quote's sentence
        for qi, quote in enumerate(self.quotes):
            if qi in bound_quotes:
                continue
            for cite in sorted_cites:
                # Quote contains the citation reference
                if _span_contains(quote.start, quote.end, cite.start, cite.end):
                    bindings.append(QuoteBinding(
                        quote=quote,
                        citation_start=cite.start,
                        confidence=0.95,
                        tier=1,
                        reason="citation embedded within quoted text",
                    ))
                    bound_quotes.add(qi)
                    break

        # Tier 2: Same sentence
        for qi, quote in enumerate(self.quotes):
            if qi in bound_quotes:
                continue
            if quote.sentence_index is None:
                continue
            # Find citations in the same sentence
            same_sent_cites = [
                c for c in sorted_cites
                if c.sentence_index == quote.sentence_index
            ]
            if len(same_sent_cites) == 1:
                # Unambiguous: one citation in the sentence
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=same_sent_cites[0].start,
                    confidence=0.90,
                    tier=2,
                    reason="quote and citation in same sentence (unambiguous)",
                ))
                bound_quotes.add(qi)
            elif same_sent_cites:
                # Multiple citations in sentence — bind to closest forward cite
                forward = [c for c in same_sent_cites if c.start >= quote.end]
                target = forward[0] if forward else same_sent_cites[-1]
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=target.start,
                    confidence=0.85,
                    tier=2,
                    reason="quote and citation in same sentence (closest forward cite)",
                ))
                bound_quotes.add(qi)

        # Tier 3b: Quote in the sentence immediately following the citation.
        # Legal writing commonly uses "[Citation]. The court held that '[quote].' Id."
        # In this pattern the quote is one sentence after the cite — still strong.
        # Run before Tier 3 so this high-confidence binding isn't preempted by a
        # weaker multi-forward-citation Tier 3 match.
        for qi, quote in enumerate(self.quotes):
            if qi in bound_quotes:
                continue
            if quote.sentence_index is None:
                continue
            # Citations in the immediately preceding sentence
            prev_cites = [
                c for c in sorted_cites
                if c.sentence_index is not None
                and c.sentence_index == quote.sentence_index - 1
            ]
            if len(prev_cites) == 1:
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=prev_cites[0].start,
                    confidence=0.75,
                    tier=3,
                    reason="quote immediately follows citation sentence",
                ))
                bound_quotes.add(qi)
            elif prev_cites:
                # Multiple cites in preceding sentence — bind to last (most recent in sentence)
                target = prev_cites[-1]
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=target.start,
                    confidence=0.72,
                    tier=3,
                    reason="quote follows sentence with citations (nearest preceding)",
                ))
                bound_quotes.add(qi)

        # Tier 3: Quote precedes citation in same paragraph, no competing cite
        for qi, quote in enumerate(self.quotes):
            if qi in bound_quotes:
                continue
            if quote.paragraph_index is None:
                continue

            same_para_cites = [
                c for c in sorted_cites
                if c.paragraph_index == quote.paragraph_index
            ]
            # Only forward citations
            forward_cites = [c for c in same_para_cites if c.start > quote.end]

            if len(forward_cites) == 1:
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=forward_cites[0].start,
                    confidence=0.75,
                    tier=3,
                    reason="quote precedes sole citation in paragraph",
                ))
                bound_quotes.add(qi)
            elif forward_cites:
                # Multiple forward cites — bind to nearest
                nearest = min(forward_cites, key=lambda c: c.start - quote.end)
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=nearest.start,
                    confidence=0.60,
                    tier=3,
                    reason="quote precedes nearest forward citation in paragraph",
                ))
                bound_quotes.add(qi)

        # Tier 4: Same paragraph, any position (weakest)
        for qi, quote in enumerate(self.quotes):
            if qi in bound_quotes:
                continue
            if quote.paragraph_index is None:
                continue

            same_para_cites = [
                c for c in sorted_cites
                if c.paragraph_index == quote.paragraph_index
            ]
            if same_para_cites:
                nearest = min(
                    same_para_cites,
                    key=lambda c: abs(c.start - quote.start),
                )
                bindings.append(QuoteBinding(
                    quote=quote,
                    citation_start=nearest.start,
                    confidence=0.50,
                    tier=4,
                    reason="quote and citation in same paragraph (weak binding)",
                ))
                bound_quotes.add(qi)

        # Sort by confidence descending
        bindings.sort(key=lambda b: -b.confidence)
        self._bindings = bindings
        return bindings

    def get_quote_for_citation(
        self, citation_start: int, citation_end: int
    ) -> Optional[Tuple[str, float]]:
        """Get the best quote bound to a specific citation.

        Returns (quote_text, confidence) or None if no binding above threshold.
        """
        bindings = self.bind()
        for b in bindings:
            if b.citation_start == citation_start and b.confidence >= self.binding_threshold:
                return (b.quote.text, b.confidence)
        # Also check by overlap (citation spans can vary slightly)
        for b in bindings:
            if (b.confidence >= self.binding_threshold and
                _spans_overlap(b.citation_start, b.citation_start + 50,
                              citation_start, citation_end)):
                return (b.quote.text, b.confidence)
        return None

    def floating_quotes(self) -> List[Quote]:
        """Return quotes that could not be bound to any citation.

        These are potential red flags — quoted text with no supporting
        citation, or quotes too far from any citation to confidently bind.
        """
        bindings = self.bind()
        bound_quote_ids = {
            id(b.quote) for b in bindings
            if b.confidence >= self.binding_threshold
        }
        return [q for q in self.quotes if id(q) not in bound_quote_ids]

    def binding_summary(self) -> Dict[str, int]:
        """Return counts by tier and floating quotes."""
        bindings = self.bind()
        above = [b for b in bindings if b.confidence >= self.binding_threshold]
        below = [b for b in bindings if b.confidence < self.binding_threshold]
        return {
            "total_quotes": len(self.quotes),
            "total_citations": len(self._citations),
            "bound_above_threshold": len(above),
            "bound_below_threshold": len(below),
            "floating_quotes": len(self.floating_quotes()),
            "tier_1": sum(1 for b in above if b.tier == 1),
            "tier_2": sum(1 for b in above if b.tier == 2),
            "tier_3": sum(1 for b in above if b.tier == 3),
            "tier_4": sum(1 for b in above if b.tier == 4),
        }

    def _find_sentence(self, char_pos: int) -> Optional[int]:
        """Find which sentence a character position falls in."""
        for i, sent in enumerate(self.sentences):
            if sent.start <= char_pos < sent.end:
                return i
        return None

    def _find_paragraph(self, char_pos: int) -> Optional[int]:
        """Find which paragraph a character position falls in."""
        for i, para in enumerate(self.paragraphs):
            if para.start <= char_pos < para.end:
                return i
        return None
