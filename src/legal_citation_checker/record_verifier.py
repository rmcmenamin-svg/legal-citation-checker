"""Verify record citations against a closed corpus of documents.

Checks:
1. Document existence — does the cited document exist in the corpus?
2. Location validity — does the cited page/paragraph/line exist?
3. Quote accuracy — does quoted text match the document at the cited location?
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import List, Optional, Tuple

from .corpus_index import CorpusIndex
from .models import RecordCitation, RecordVerificationResult

logger = logging.getLogger("citation-checker")

# Minimum similarity ratio for quote matching
QUOTE_MATCH_THRESHOLD = 0.80
QUOTE_MATCH_GOOD = 0.90


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for fuzzy comparison: collapse whitespace, normalize quotes."""
    import re as _re
    # Normalize smart quotes to plain quotes
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2014", "--").replace("\u2013", "-")
    # Strip California line-number artifacts: newline followed by 1-2 digits
    # e.g. "be\n11 notified" → "be notified"
    text = _re.sub(r"\n\s*\d{1,2}\s+", " ", text)
    return " ".join(text.split())


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace and strip for comparison."""
    return _normalize_for_comparison(text)


def _fuzzy_quote_match(
    needle: str, haystack: str, threshold: float = QUOTE_MATCH_THRESHOLD
) -> Tuple[bool, float, Optional[str]]:
    """Check if `needle` appears in `haystack` with fuzzy matching.

    Returns (matched, similarity, best_match_text).
    """
    if not needle or not haystack:
        return (False, 0.0, None)

    needle_norm = _normalize_whitespace(needle.lower())
    haystack_norm = _normalize_whitespace(haystack.lower())

    # Exact substring check first
    if needle_norm in haystack_norm:
        return (True, 1.0, needle)

    # For short quotes, also try after stripping trailing/leading punctuation.
    # "be notified." won't exact-match '"be notified,"' but core words will.
    import re as _re2
    needle_core = _re2.sub(r'^["\'\s]+|["\'\s.,;:!?]+$', '', needle_norm)
    if needle_core and len(needle_core) >= 5 and needle_core in haystack_norm:
        return (True, 0.95, needle)

    # Sliding window fuzzy match
    needle_len = len(needle_norm)
    best_ratio = 0.0
    best_text = None

    # Use SequenceMatcher for windowed comparison
    if len(haystack_norm) < needle_len:
        ratio = difflib.SequenceMatcher(None, needle_norm, haystack_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_text = haystack[:len(haystack)]
    else:
        # Slide a window of size ~needle_len across haystack
        step = max(1, needle_len // 4)
        for i in range(0, len(haystack_norm) - needle_len + 1, step):
            window = haystack_norm[i : i + needle_len + 20]  # slight oversize
            ratio = difflib.SequenceMatcher(None, needle_norm, window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                # Get the original-case text
                best_text = haystack[i : i + needle_len + 20].strip()

    return (best_ratio >= threshold, best_ratio, best_text)


def _search_full_document(
    needle: str, doc_text: str, threshold: float = QUOTE_MATCH_THRESHOLD
) -> Tuple[bool, float, Optional[str]]:
    """Search the entire document text for a quote match."""
    return _fuzzy_quote_match(needle, doc_text, threshold)


def _parse_range(ref: str) -> Tuple[int, Optional[int]]:
    """Parse a reference like '34' or '12-15' into (start, end)."""
    if "-" in ref or "–" in ref:
        parts = re.split(r"[-–]", ref)
        return (int(parts[0].strip()), int(parts[1].strip()))
    return (int(ref.strip()), None)


class RecordVerifier:
    """Verify record citations against a closed corpus."""

    def __init__(self, corpus: CorpusIndex):
        self.corpus = corpus

    def verify(self, citation: RecordCitation) -> RecordVerificationResult:
        """Verify a single record citation.

        Checks in order:
        1. Document existence
        2. Location validity (page/paragraph/line)
        3. Quote accuracy (if quoted text is available)
        """
        # Step 1: Find the document
        doc = self.corpus.find_document(citation.document_label)
        if doc is None:
            return RecordVerificationResult(
                status="Document Not Found",
                confidence=90,
                evidence=(
                    f"No document matching '{citation.document_label}' found in corpus. "
                    f"Available documents: {', '.join(self.corpus.document_labels)}"
                ),
            )

        # Step 2: Check location
        location_result = self._check_location(citation, doc)
        if location_result is not None:
            # If we have quoted text, also try to find it elsewhere
            if citation.quoted_text and location_result.status == "Location Mismatch":
                found, similarity, match_text = _search_full_document(
                    citation.quoted_text, doc.full_text
                )
                if found:
                    location_result = RecordVerificationResult(
                        status="Location Mismatch",
                        confidence=85,
                        evidence=(
                            f"{location_result.evidence} However, the quoted text "
                            f"was found elsewhere in the document "
                            f"(similarity: {similarity:.0%})."
                        ),
                        matched_document=doc.label,
                        matched_text=match_text,
                        suggested_location="Found elsewhere in document",
                        quote_similarity=similarity,
                    )
            return location_result

        # Step 3: Check quoted text at the cited location
        if citation.quoted_text:
            return self._check_quote(citation, doc)

        # Everything checks out (document exists, location valid, no quote to check)
        return RecordVerificationResult(
            status="Verified",
            confidence=85,
            evidence=f"Document '{doc.label}' found in corpus; cited location exists.",
            matched_document=doc.label,
        )

    def _check_location(
        self, citation: RecordCitation, doc
    ) -> Optional[RecordVerificationResult]:
        """Check if the cited location exists in the document.

        Returns None if location is valid, or a RecordVerificationResult
        if there's a problem.
        """
        # Check paragraph reference
        if citation.paragraph_ref:
            start, end = _parse_range(citation.paragraph_ref)
            if doc.paragraphs:
                max_para = max(doc.paragraphs.keys()) if doc.paragraphs else 0
                if start > max_para:
                    return RecordVerificationResult(
                        status="Location Mismatch",
                        confidence=92,
                        evidence=(
                            f"Document '{doc.label}' has {max_para} numbered paragraphs, "
                            f"but citation references ¶ {citation.paragraph_ref}."
                        ),
                        matched_document=doc.label,
                    )
                if end and end > max_para:
                    return RecordVerificationResult(
                        status="Location Mismatch",
                        confidence=92,
                        evidence=(
                            f"Document '{doc.label}' has {max_para} numbered paragraphs, "
                            f"but citation references ¶¶ {citation.paragraph_ref}."
                        ),
                        matched_document=doc.label,
                    )
            # If no numbered paragraphs were extracted, we can't verify
            # but we don't flag it as a mismatch

        # Check page reference
        if citation.page_ref:
            start, end = _parse_range(citation.page_ref)
            if doc.pages:
                max_page = max(doc.pages.keys()) if doc.pages else 0
                if start > max_page:
                    return RecordVerificationResult(
                        status="Location Mismatch",
                        confidence=90,
                        evidence=(
                            f"Document '{doc.label}' has {max_page} pages, "
                            f"but citation references page {citation.page_ref}."
                        ),
                        matched_document=doc.label,
                    )

        # Check line reference (depositions/transcripts)
        if citation.line_ref and citation.page_ref:
            page_num, _ = _parse_range(citation.page_ref)
            line_start, line_end = _parse_range(citation.line_ref)

            # Check if the page:line exists
            key = f"{page_num}:{line_start}"
            if doc.lines and key not in doc.lines:
                # Page might exist but line doesn't
                page_text = doc.pages.get(page_num)
                if page_text is not None:
                    return RecordVerificationResult(
                        status="Location Mismatch",
                        confidence=88,
                        evidence=(
                            f"Page {page_num} exists in '{doc.label}', but "
                            f"line {line_start} was not found on that page."
                        ),
                        matched_document=doc.label,
                    )

        return None  # Location is valid

    def _check_quote(
        self, citation: RecordCitation, doc
    ) -> RecordVerificationResult:
        """Check if the quoted text matches the document at the cited location."""
        quote = citation.quoted_text
        if not quote:
            return RecordVerificationResult(
                status="Verified",
                confidence=85,
                evidence=f"Document '{doc.label}' found in corpus; cited location exists.",
                matched_document=doc.label,
            )

        # Get text at the specific location
        location_text = self._get_text_at_location(citation, doc)

        if location_text:
            matched, similarity, match_text = _fuzzy_quote_match(quote, location_text)
            if matched:
                conf = 95 if similarity >= QUOTE_MATCH_GOOD else 85
                return RecordVerificationResult(
                    status="Verified",
                    confidence=conf,
                    evidence=(
                        f"Quote found in '{doc.label}' at cited location "
                        f"(similarity: {similarity:.0%})."
                    ),
                    matched_document=doc.label,
                    matched_text=match_text,
                    quote_similarity=similarity,
                )

        # Quote not found at cited location — search entire document
        found, similarity, match_text = _search_full_document(quote, doc.full_text)
        if found:
            return RecordVerificationResult(
                status="Quote Mismatch",
                confidence=80,
                evidence=(
                    f"Quote not found at the cited location in '{doc.label}', "
                    f"but similar text was found elsewhere in the document "
                    f"(similarity: {similarity:.0%})."
                ),
                matched_document=doc.label,
                matched_text=match_text,
                suggested_location="Found elsewhere in document",
                quote_similarity=similarity,
            )

        # Quote not found anywhere in the document
        return RecordVerificationResult(
            status="Quote Mismatch",
            confidence=90,
            evidence=(
                f"Quoted text not found in '{doc.label}'. "
                f"The document exists but does not contain the cited text."
            ),
            matched_document=doc.label,
            quote_similarity=0.0,
        )

    def _get_text_at_location(self, citation: RecordCitation, doc) -> Optional[str]:
        """Get the text at the specific cited location."""
        # Paragraph reference
        if citation.paragraph_ref:
            start, end = _parse_range(citation.paragraph_ref)
            if doc.paragraphs:
                parts = []
                for p in range(start, (end or start) + 1):
                    text = doc.paragraphs.get(p)
                    if text:
                        parts.append(text)
                if parts:
                    return " ".join(parts)

        # Line reference (deposition/transcript)
        if citation.line_ref and citation.page_ref:
            page_num, _ = _parse_range(citation.page_ref)
            line_start, line_end = _parse_range(citation.line_ref)
            text = self.corpus.get_line_range_text(
                doc.label, page_num, line_start, line_end or line_start
            )
            if text:
                return text

        # Page reference
        if citation.page_ref:
            start, _ = _parse_range(citation.page_ref)
            return doc.pages.get(start)

        # Fall back to full document text
        return doc.full_text


def verify_record_citations(
    citations: List[RecordCitation],
    corpus: CorpusIndex,
) -> List[Tuple[RecordCitation, RecordVerificationResult]]:
    """Verify all record citations against a corpus.

    Returns a list of (citation, result) tuples.
    """
    verifier = RecordVerifier(corpus)
    results = []
    for citation in citations:
        result = verifier.verify(citation)
        results.append((citation, result))
        logger.info(
            f"  {citation.raw_text} -> {result.status} ({result.confidence}%)"
        )
    return results
