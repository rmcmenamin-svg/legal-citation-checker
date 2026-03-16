"""Extract record citations from legal briefs.

Record citations reference documents within a case record — exhibits,
depositions, complaints, declarations, docket entries, and transcripts.
These are structurally different from case-law citations and require
regex-based extraction rather than eyecite.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from .models import DocumentText, RecordCitation

# ── Regex patterns ──────────────────────────────────────────────────────
# Each entry: (compiled regex, document_type, group-to-field mapping notes)
#
# Groups are named for clarity. Optional party prefix (Pl.'s / Def.'s)
# is captured outside the main patterns via PARTY_PREFIX_RE.

PARTY_PREFIX_RE = re.compile(
    r"(?:(?P<party>Pl(?:aintiff)?(?:'s|s')?|Def(?:endant)?(?:'s|s')?|"
    r"Third[- ]Party\s+(?:Pl(?:aintiff)?|Def(?:endant)?)(?:'s|s')?)\s+)",
    re.IGNORECASE,
)

# Exhibit references: "Exhibit A", "Ex. C at 3", "Pl.'s Ex. 12", "Exhibit 4 at 7-8"
# Uses word boundary \b and requires the Ex/Exhibit keyword to NOT be part of a larger word.
EXHIBIT_RE = re.compile(
    r"(?P<party>(?:Pl(?:aintiff)?(?:'s|s')?|Def(?:endant)?(?:'s|s')?|"
    r"Third[- ]Party\s+(?:Pl(?:aintiff)?|Def(?:endant)?)(?:'s|s')?)\s+)?"
    r"(?:Exhibit\s+(?P<label1>[A-Z]{1,3}|\d{1,4})"
    r"|Ex(?:h)?\.?\s+(?P<label2>[A-Z]{1,3}|\d{1,4}))"
    r"(?:\s+at\s+(?P<page>\d+(?:\s*[-–]\s*\d+)?))?",
)

# Deposition references: "Smith Dep. 45:12-15", "Dep. of Jane Doe, 112:3-8"
# Also handles "Smith Dep. at 45:12"
DEPOSITION_RE = re.compile(
    r"(?:"
    # Form 1: "Name Dep. page:line"
    r"(?P<witness1>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))\s+"
    r"Dep(?:osition)?\.?\s*(?:at\s+)?(?P<page1>\d+):(?P<line1>\d+)(?:\s*[-–]\s*(?P<line_end1>\d+))?"
    r"|"
    # Form 2: "Dep. of Name, page:line"
    r"Dep(?:osition)?\.?\s+of\s+(?P<witness2>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))"
    r"(?:\s*,\s*|\s+at\s+|\s+)(?P<page2>\d+):(?P<line2>\d+)(?:\s*[-–]\s*(?P<line_end2>\d+))?"
    r"|"
    # Form 3: "Name Dep. at page" (no line ref)
    r"(?P<witness3>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))\s+"
    r"Dep(?:osition)?\.?\s*(?:at\s+)?(?P<page3>\d+)(?::(?P<line3>\d+)(?:\s*[-–]\s*(?P<line_end3>\d+))?)?"
    r")",
    re.IGNORECASE,
)

# Complaint paragraph references: "Compl. ¶ 34", "Complaint ¶¶ 12-15", "Compl. at ¶ 7"
COMPLAINT_RE = re.compile(
    r"Compl(?:aint)?\.?\s*(?:at\s+)?[¶P]\s*[¶P]?\s*(?P<para>\d+)"
    r"(?:\s*[-–]\s*(?P<para_end>\d+))?",
    re.IGNORECASE,
)

# Declaration/Affidavit: "Smith Decl. ¶ 8", "Aff. of Johnson ¶ 14", "Johnson Aff. ¶ 3"
DECLARATION_RE = re.compile(
    r"(?:"
    # Form 1: "Name Decl./Aff. ¶ N"
    r"(?P<witness1>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))\s+"
    r"(?:Decl(?:aration)?|Aff(?:idavit)?)\.?\s*(?:at\s+)?[¶P]\s*(?P<para1>\d+)"
    r"|"
    # Form 2: "Decl./Aff. of Name ¶ N"
    r"(?:Decl(?:aration)?|Aff(?:idavit)?)\.?\s+of\s+"
    r"(?P<witness2>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))"
    r"(?:\s*,?\s*|\s+at\s+|\s+)[¶P]\s*(?P<para2>\d+)"
    r")",
    re.IGNORECASE,
)

# Docket/ECF entries: "Dkt. No. 42", "ECF No. 15 at 7", "D.E. 23"
DOCKET_ENTRY_RE = re.compile(
    r"(?:Dkt|ECF|D\.E\.|Doc)\.?\s*(?:No\.?\s*)?(?P<number>\d+)"
    r"(?:\s+at\s+(?P<page>\d+))?",
    re.IGNORECASE,
)

# Trial/hearing transcript: "Tr. 234:5-10", "Trial Tr. Vol. II, 56:1-4", "Hr'g Tr. 12:5"
TRANSCRIPT_RE = re.compile(
    r"(?:(?:Trial|Hr'g|Hearing)\s+)?Tr(?:ial)?\.?\s*"
    r"(?:Vol\.?\s*(?P<volume>[IVX]+|\d+)\s*,?\s*)?"
    r"(?P<page>\d+):(?P<line>\d+)(?:\s*[-–]\s*(?P<line_end>\d+))?",
    re.IGNORECASE,
)

# Answer paragraph references: "Answer ¶ 12", "Ans. ¶¶ 5-8"
ANSWER_RE = re.compile(
    r"Ans(?:wer)?\.?\s*(?:at\s+)?[¶P]\s*[¶P]?\s*(?P<para>\d+)"
    r"(?:\s*[-–]\s*(?P<para_end>\d+))?",
    re.IGNORECASE,
)

# Order references: "Order at 3", "Order dated Jan. 5, 2024, at 3"
# We don't try to parse the date — just capture the page
ORDER_RE = re.compile(
    r"Order\s+(?:dated\s+[A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}\s*,?\s*)?"
    r"at\s+(?P<page>\d+)",
    re.IGNORECASE,
)


# All patterns in priority order (more specific patterns first)
PATTERNS: List[Tuple[re.Pattern, str]] = [
    (DEPOSITION_RE, "deposition"),
    (TRANSCRIPT_RE, "transcript"),
    (DECLARATION_RE, "declaration"),
    (COMPLAINT_RE, "complaint"),
    (ANSWER_RE, "answer"),
    (EXHIBIT_RE, "exhibit"),
    (DOCKET_ENTRY_RE, "docket"),
    (ORDER_RE, "order"),
]


def _find_nearby_quote(text: str, pos: int, max_distance: int = 300) -> Optional[str]:
    """Find the nearest quoted text within max_distance chars of pos.

    Looks both before and after the citation for material in quotation marks.
    """
    start = max(0, pos - max_distance)
    end = min(len(text), pos + max_distance)
    window = text[start:end]

    # Look for quoted text (double quotes or smart quotes)
    quote_re = re.compile(r'["\u201c](.+?)["\u201d]', re.DOTALL)
    matches = list(quote_re.finditer(window))
    if not matches:
        return None

    # Return the quote closest to the citation position
    cite_offset = pos - start
    best = min(matches, key=lambda m: abs(m.start() - cite_offset))
    quote_text = best.group(1).strip()
    # Only return substantive quotes (not single words)
    if len(quote_text) > 10:
        return quote_text
    return None


def _get_context(text: str, start: int, end: int, context_chars: int = 200) -> str:
    """Get surrounding context for a citation."""
    ctx_start = max(0, start - context_chars)
    ctx_end = min(len(text), end + context_chars)
    return text[ctx_start:ctx_end].strip()


def _find_paragraph_index(doc: DocumentText, char_pos: int) -> Optional[int]:
    """Find which paragraph a character position falls in."""
    for para in doc.paragraphs:
        if para.start <= char_pos < para.end:
            return para.index
    return None


def _parse_exhibit(match: re.Match) -> RecordCitation:
    """Parse an exhibit citation from a regex match."""
    party = (match.group("party") or "").strip() or None
    label = match.group("label1") or match.group("label2")
    page = match.group("page")

    # Normalize label: "a" -> "A"
    if label and label.isalpha():
        label = label.upper()

    return RecordCitation(
        document_label=f"Exhibit {label}",
        document_type="exhibit",
        page_ref=page,
        party_prefix=party,
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


def _parse_deposition(match: re.Match) -> RecordCitation:
    """Parse a deposition citation from a regex match."""
    # Try each form
    witness = match.group("witness1") or match.group("witness2") or match.group("witness3") or ""
    page = match.group("page1") or match.group("page2") or match.group("page3")
    line = match.group("line1") or match.group("line2") or match.group("line3")
    line_end = match.group("line_end1") or match.group("line_end2") or match.group("line_end3")

    line_ref = None
    if line:
        line_ref = f"{line}-{line_end}" if line_end else line

    return RecordCitation(
        document_label=f"{witness} Dep." if witness else "Dep.",
        document_type="deposition",
        page_ref=page,
        line_ref=line_ref,
        witness_name=witness or None,
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


def _parse_complaint(match: re.Match) -> RecordCitation:
    """Parse a complaint paragraph citation."""
    para = match.group("para")
    para_end = match.group("para_end")
    para_ref = f"{para}-{para_end}" if para_end else para

    return RecordCitation(
        document_label="Complaint",
        document_type="complaint",
        paragraph_ref=para_ref,
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


def _parse_declaration(match: re.Match) -> RecordCitation:
    """Parse a declaration/affidavit citation."""
    witness = match.group("witness1") or match.group("witness2") or ""
    para = match.group("para1") or match.group("para2")

    doc_type_word = "Decl." if "decl" in match.group(0).lower() else "Aff."

    return RecordCitation(
        document_label=f"{witness} {doc_type_word}" if witness else doc_type_word,
        document_type="declaration",
        paragraph_ref=para,
        witness_name=witness or None,
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


def _parse_docket(match: re.Match) -> RecordCitation:
    """Parse a docket/ECF entry citation."""
    number = match.group("number")
    page = match.group("page")

    # Determine the prefix for the label
    raw = match.group(0)
    if "ECF" in raw.upper():
        prefix = "ECF"
    elif "D.E." in raw:
        prefix = "D.E."
    elif "Doc" in raw:
        prefix = "Doc."
    else:
        prefix = "Dkt."

    return RecordCitation(
        document_label=f"{prefix} {number}",
        document_type="docket",
        page_ref=page,
        raw_text=raw,
        span=(match.start(), match.end()),
    )


def _parse_transcript(match: re.Match) -> RecordCitation:
    """Parse a trial/hearing transcript citation."""
    page = match.group("page")
    line = match.group("line")
    line_end = match.group("line_end")

    line_ref = None
    if line:
        line_ref = f"{line}-{line_end}" if line_end else line

    raw = match.group(0)
    label = "Trial Tr."
    if "hr'g" in raw.lower() or "hearing" in raw.lower():
        label = "Hr'g Tr."

    return RecordCitation(
        document_label=label,
        document_type="transcript",
        page_ref=page,
        line_ref=line_ref,
        raw_text=raw,
        span=(match.start(), match.end()),
    )


def _parse_answer(match: re.Match) -> RecordCitation:
    """Parse an answer paragraph citation."""
    para = match.group("para")
    para_end = match.group("para_end")
    para_ref = f"{para}-{para_end}" if para_end else para

    return RecordCitation(
        document_label="Answer",
        document_type="answer",
        paragraph_ref=para_ref,
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


def _parse_order(match: re.Match) -> RecordCitation:
    """Parse a court order citation."""
    return RecordCitation(
        document_label="Order",
        document_type="order",
        page_ref=match.group("page"),
        raw_text=match.group(0),
        span=(match.start(), match.end()),
    )


# Map document_type -> parser function
_PARSERS = {
    "exhibit": _parse_exhibit,
    "deposition": _parse_deposition,
    "complaint": _parse_complaint,
    "declaration": _parse_declaration,
    "docket": _parse_docket,
    "transcript": _parse_transcript,
    "answer": _parse_answer,
    "order": _parse_order,
}


def extract_record_citations(doc: DocumentText) -> List[RecordCitation]:
    """Extract all record citations from a document.

    Returns a list of RecordCitation objects, deduplicated by span
    (a citation matched by a more specific pattern takes priority).
    """
    text = doc.full_text
    results: List[RecordCitation] = []
    # Track matched spans to avoid overlapping matches
    used_spans: List[Tuple[int, int]] = []

    for pattern, doc_type in PATTERNS:
        parser = _PARSERS[doc_type]
        for match in pattern.finditer(text):
            span = (match.start(), match.end())

            # Skip if this span overlaps with a previously matched span
            overlaps = any(
                not (span[1] <= us[0] or span[0] >= us[1])
                for us in used_spans
            )
            if overlaps:
                continue

            citation = parser(match)
            citation.span = span
            citation.context = _get_context(text, span[0], span[1])
            citation.paragraph_index = _find_paragraph_index(doc, span[0])
            citation.quoted_text = _find_nearby_quote(text, span[0])

            results.append(citation)
            used_spans.append(span)

    # Sort by position in document
    results.sort(key=lambda c: c.span[0])
    return results
