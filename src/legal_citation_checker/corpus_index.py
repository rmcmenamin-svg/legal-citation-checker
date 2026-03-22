"""Closed-corpus document indexing.

Ingests uploaded source documents (exhibits, depositions, complaints, etc.)
and builds searchable page/paragraph/line indices for record citation
verification.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import CorpusDocument, DocumentText

logger = logging.getLogger("citation-checker")

# ── Document type detection from filename ──────────────────────────────

# Specific types checked before generic "exhibit" so that
# "Ex. 5 - Smith Declaration.pdf" is typed as "declaration", not "exhibit".
_TYPE_PATTERNS = [
    (re.compile(r"dep(?:osition)?", re.IGNORECASE), "deposition"),
    (re.compile(r"transcript|tr[_\s\-]", re.IGNORECASE), "transcript"),
    (re.compile(r"decl(?:aration)?", re.IGNORECASE), "declaration"),
    (re.compile(r"aff(?:idavit)?", re.IGNORECASE), "declaration"),
    (re.compile(r"complaint", re.IGNORECASE), "complaint"),
    (re.compile(r"answer", re.IGNORECASE), "answer"),
    (re.compile(r"order", re.IGNORECASE), "order"),
    (re.compile(r"(?:dkt|ecf|doc)[_\s\-]*\d+", re.IGNORECASE), "docket"),
    (re.compile(r"exhibit[_\s\-]*([A-Z]|\d+)", re.IGNORECASE), "exhibit"),
    (re.compile(r"\bex[_\.\s\-]*\d+\b", re.IGNORECASE), "exhibit"),
]


def _detect_document_type(filename: str) -> str:
    """Guess document type from filename."""
    for pattern, doc_type in _TYPE_PATTERNS:
        if pattern.search(filename):
            return doc_type
    return "unknown"


def _filename_to_label(filename: str) -> str:
    """Convert a filename to a human-readable document label.

    Examples:
        "Exhibit_A.pdf" -> "Exhibit A"
        "Smith_Deposition.docx" -> "Smith Deposition"
        "complaint.docx" -> "Complaint"
    """
    stem = Path(filename).stem
    # Replace underscores and hyphens with spaces
    label = stem.replace("_", " ").replace("-", " ")
    # Title-case if all lowercase
    if label == label.lower():
        label = label.title()
    return label.strip()


# ── Paragraph numbering for complaints/declarations ────────────────────

# Plain "1. text" format
_PARA_NUMBER_RE = re.compile(r"^\s*(\d+)\.\s+")
# California line-numbered format: "25 6. text" — line number then para number
_CA_LINE_PARA_RE = re.compile(r"^\s*\d{1,2}\s+(\d+)\.\s+(.+)$")


def _extract_numbered_paragraphs(text: str) -> Dict[int, str]:
    """Extract numbered paragraphs from a complaint or declaration.

    Handles two formats:
    - Plain: "1. ...", "2. ..."
    - California line-numbered: "25 6. Plaintiffs..." (line num then para num)
    """
    paragraphs: Dict[int, str] = {}
    current_num = None
    current_lines: List[str] = []

    # Detect California line-numbered format by scanning the full text.
    # We can't limit to first N lines because cover pages and exhibit headers
    # may precede the declaration body.
    all_lines = text.split("\n")
    ca_matches = sum(1 for line in all_lines if _CA_LINE_PARA_RE.match(line.strip()))
    use_ca_format = ca_matches >= 5

    for line in all_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if use_ca_format:
            m = _CA_LINE_PARA_RE.match(stripped)
            if m:
                if current_num is not None:
                    paragraphs[current_num] = " ".join(current_lines).strip()
                current_num = int(m.group(1))
                current_lines = [m.group(2).strip()]
                continue
            # Continuation line: starts with a line number only
            cont = re.match(r"^\s*\d{1,2}\s+(.+)$", stripped)
            if cont and current_num is not None:
                current_lines.append(cont.group(1).strip())
            continue

        # Plain format
        m = _PARA_NUMBER_RE.match(stripped)
        if m:
            if current_num is not None:
                paragraphs[current_num] = " ".join(current_lines).strip()
            current_num = int(m.group(1))
            current_lines = [stripped[m.end():].strip()]
        elif current_num is not None:
            current_lines.append(stripped)

    # Save last paragraph
    if current_num is not None:
        paragraphs[current_num] = " ".join(current_lines).strip()

    return paragraphs


# ── Deposition page:line parsing ───────────────────────────────────────

_DEPO_PAGE_HEADER_RE = re.compile(r"^\s*(?:Page\s+)?(\d+)\s*$")
_DEPO_LINE_RE = re.compile(r"^\s*(\d{1,2})\s+(.+)$")


def _extract_deposition_lines(text: str) -> Tuple[Dict[int, str], Dict[str, str]]:
    """Extract page-indexed and page:line-indexed text from a deposition.

    Returns:
        (pages, lines) where:
        - pages: {page_num: full_page_text}
        - lines: {"page:line": line_text}

    Deposition transcripts typically have pages numbered 1-N with
    lines numbered 1-25 per page.
    """
    pages: Dict[int, str] = {}
    lines: Dict[str, str] = {}

    current_page: Optional[int] = None
    current_page_lines: List[str] = []
    current_line_num = 0

    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Check for page header
        page_match = _DEPO_PAGE_HEADER_RE.match(stripped)
        if page_match:
            # Save previous page
            if current_page is not None:
                pages[current_page] = "\n".join(current_page_lines)
            current_page = int(page_match.group(1))
            current_page_lines = []
            current_line_num = 0
            continue

        # Check for numbered line
        line_match = _DEPO_LINE_RE.match(stripped)
        if line_match and current_page is not None:
            line_num = int(line_match.group(1))
            line_text = line_match.group(2).strip()
            lines[f"{current_page}:{line_num}"] = line_text
            current_page_lines.append(line_text)
            current_line_num = line_num
        elif current_page is not None:
            # Continuation line
            current_page_lines.append(stripped)
            # If there are numbered lines, add as continuation of last
            if current_line_num > 0:
                key = f"{current_page}:{current_line_num}"
                if key in lines:
                    lines[key] += " " + stripped

    # Save last page
    if current_page is not None:
        pages[current_page] = "\n".join(current_page_lines)

    return pages, lines


# ── Text extraction helpers ────────────────────────────────────────────

def _extract_text(path: Path) -> DocumentText:
    """Extract text from a document, supporting DOCX, PDF, and plain text."""
    suffix = path.suffix.lower()

    if suffix == ".docx":
        from .extractors import extract_docx_text
        return extract_docx_text(path)
    elif suffix == ".pdf":
        from .extractors import extract_pdf_text
        return extract_pdf_text(path)
    elif suffix in (".txt", ".text"):
        text = path.read_text(encoding="utf-8", errors="replace")
        from .models import ParagraphSpan
        # Split by double newlines for paragraph boundaries
        paragraphs = []
        cursor = 0
        for i, para in enumerate(text.split("\n\n"), start=1):
            para = para.strip()
            if not para:
                continue
            start = text.index(para, cursor) if para in text[cursor:] else cursor
            paragraphs.append(ParagraphSpan(index=i, text=para, start=start, end=start + len(para)))
            cursor = start + len(para)
        return DocumentText(full_text=text, paragraphs=paragraphs)
    else:
        raise ValueError(f"Unsupported document format: {suffix}")


def _extract_pages_from_document_text(doc: DocumentText) -> Dict[int, str]:
    """Build a page index from DocumentText paragraphs.

    For PDFs, paragraphs correspond to pages. For DOCX, we use paragraph
    indices as a rough proxy (since DOCX doesn't have intrinsic pages).
    """
    return {para.index: para.text for para in doc.paragraphs}


# ── Corpus Index ───────────────────────────────────────────────────────

class CorpusIndex:
    """Searchable index of uploaded source documents.

    Usage:
        index = CorpusIndex.from_directory("/path/to/corpus/")
        doc = index.find_document("Exhibit A")
        text = index.get_page_text("Exhibit A", page=3)
    """

    def __init__(self, documents: Optional[List[CorpusDocument]] = None):
        self.documents: List[CorpusDocument] = documents or []
        self._label_map: Dict[str, CorpusDocument] = {}
        self._rebuild_index()

    # Regex to detect exhibit-prefixed labels like "Ex. 12", "Ex 3", "Exh. A"
    _EX_PREFIX_RE = re.compile(
        r'^(ex[h]?\.?\s*)(\d+|[A-Za-z])\b', re.IGNORECASE
    )

    def _rebuild_index(self) -> None:
        """Rebuild the label lookup index."""
        self._label_map.clear()
        for doc in self.documents:
            # Index by exact label
            self._label_map[doc.label.lower()] = doc
            # Also index by common abbreviations
            if doc.document_type == "exhibit":
                # "Exhibit A" -> also index as "Ex. A", "Ex A"
                for prefix in ("Ex.", "Ex", "Exh."):
                    short = doc.label.replace("Exhibit", prefix)
                    self._label_map[short.lower()] = doc
            elif doc.document_type == "complaint":
                for alias in ("Compl.", "Compl"):
                    self._label_map[alias.lower()] = doc
            elif doc.document_type == "answer":
                for alias in ("Ans.", "Ans"):
                    self._label_map[alias.lower()] = doc

            # For labels starting with "Ex. N", "Ex N", "Exh. N" (regardless of
            # document_type — e.g. a deposition file named "Ex. 12 - de Baere..."),
            # add "Exhibit N" and all short-form aliases so both directions match.
            ex_match = self._EX_PREFIX_RE.match(doc.label)
            if ex_match and "exhibit" not in doc.label.lower():
                num = ex_match.group(2)
                self._label_map[f"exhibit {num}".lower()] = doc
                for prefix in ("Ex.", "Ex", "Exh."):
                    self._label_map[f"{prefix} {num}".lower()] = doc
                    self._label_map[f"{prefix}{num}".lower()] = doc

    @classmethod
    def from_directory(cls, corpus_dir: str | Path) -> "CorpusIndex":
        """Load all documents from a directory.

        Filenames are used as document labels:
            Exhibit_A.pdf -> "Exhibit A"
            Smith_Deposition.docx -> "Smith Deposition"
        """
        corpus_path = Path(corpus_dir)
        if not corpus_path.is_dir():
            raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

        documents: List[CorpusDocument] = []
        supported = {".docx", ".pdf", ".txt", ".text"}

        for file_path in sorted(corpus_path.iterdir()):
            if file_path.suffix.lower() not in supported:
                continue
            if file_path.name.startswith("."):
                continue

            try:
                doc = _ingest_document(file_path)
                documents.append(doc)
                logger.info(
                    f"Indexed: {doc.label} ({doc.document_type}) — "
                    f"{doc.page_count} pages, {doc.paragraph_count} paragraphs"
                )
            except Exception as e:
                logger.warning(f"Failed to ingest {file_path.name}: {e}")

        return cls(documents=documents)

    @classmethod
    def from_manifest(cls, manifest: Dict[str, str]) -> "CorpusIndex":
        """Load documents from an explicit label-to-path mapping.

        Args:
            manifest: {"Exhibit A": "/path/to/exhibit_a.pdf", ...}
        """
        documents: List[CorpusDocument] = []
        for label, path_str in manifest.items():
            path = Path(path_str)
            if not path.exists():
                logger.warning(f"Document not found: {path_str} (label: {label})")
                continue
            try:
                doc = _ingest_document(path, label_override=label)
                documents.append(doc)
            except Exception as e:
                logger.warning(f"Failed to ingest {label}: {e}")

        return cls(documents=documents)

    # Regex to normalise "Exhibit N" / "Exhibit A" queries to "ex. N" for lookup
    _EXHIBIT_NORM_RE = re.compile(
        r'^exhibit\s+(\d+|[A-Za-z])\b', re.IGNORECASE
    )

    def find_document(self, label: str) -> Optional[CorpusDocument]:
        """Find a document by label (case-insensitive, fuzzy)."""
        # Exact match first
        key = label.lower().strip()
        if key in self._label_map:
            return self._label_map[key]

        # Try stripping trailing periods and possessives
        cleaned = key.rstrip(".")
        if cleaned in self._label_map:
            return self._label_map[cleaned]

        # Normalise "Exhibit N" -> "ex. N" so it matches docs filed as "Ex. 12 - ..."
        ex_norm = self._EXHIBIT_NORM_RE.match(key)
        if ex_norm:
            num = ex_norm.group(1)
            for alt in (f"ex. {num}", f"ex {num}", f"exh. {num}", f"exhibit {num}"):
                if alt in self._label_map:
                    return self._label_map[alt]

        # Try fuzzy: look for label as substring of any indexed label.
        # Use word-boundary check to prevent "ex. 1" from matching "ex. 10".
        def _word_boundary_match(needle: str, haystack: str) -> bool:
            pos = haystack.find(needle)
            if pos == -1:
                return False
            end = pos + len(needle)
            # The character immediately after the match must not be alphanumeric
            return end >= len(haystack) or not haystack[end].isalnum()

        for indexed_label, doc in self._label_map.items():
            if _word_boundary_match(key, indexed_label) or _word_boundary_match(indexed_label, key):
                return doc

        # Deposition special case: "Smith Dep." -> look for any doc with
        # "smith" in label (no type check — file may be typed as "exhibit")
        if "dep" in key:
            name_part = key.split("dep")[0].strip().rstrip(". ")
            if name_part:
                for doc in self.documents:
                    if name_part in doc.label.lower():
                        return doc

        # Declaration/Affidavit special case
        if "decl" in key or "aff" in key:
            name_part = re.split(r"(?:decl|aff)", key, flags=re.IGNORECASE)[0].strip().rstrip(". ")
            if name_part:
                for doc in self.documents:
                    if name_part in doc.label.lower():
                        return doc

        return None

    def get_page_text(self, label: str, page: int) -> Optional[str]:
        """Get the text of a specific page in a document."""
        doc = self.find_document(label)
        if doc is None:
            return None
        return doc.pages.get(page)

    def get_paragraph_text(self, label: str, paragraph: int) -> Optional[str]:
        """Get the text of a specific numbered paragraph."""
        doc = self.find_document(label)
        if doc is None:
            return None
        return doc.paragraphs.get(paragraph)

    def get_line_text(self, label: str, page: int, line: int) -> Optional[str]:
        """Get the text at a specific page:line in a deposition/transcript."""
        doc = self.find_document(label)
        if doc is None:
            return None
        return doc.lines.get(f"{page}:{line}")

    def get_line_range_text(
        self, label: str, page: int, start_line: int, end_line: int
    ) -> Optional[str]:
        """Get concatenated text from a range of lines."""
        doc = self.find_document(label)
        if doc is None:
            return None
        parts = []
        for line_num in range(start_line, end_line + 1):
            text = doc.lines.get(f"{page}:{line_num}")
            if text:
                parts.append(text)
        return " ".join(parts) if parts else None

    @property
    def document_labels(self) -> List[str]:
        """List all indexed document labels."""
        return [doc.label for doc in self.documents]


def _ingest_document(
    path: Path,
    label_override: Optional[str] = None,
) -> CorpusDocument:
    """Ingest a single document into a CorpusDocument with indices."""
    label = label_override or _filename_to_label(path.name)
    doc_type = _detect_document_type(path.name)

    # Override type based on label if given
    if label_override:
        doc_type = _detect_document_type(label_override) or doc_type

    doc_text = _extract_text(path)
    full_text = doc_text.full_text

    # Build page index
    pages = _extract_pages_from_document_text(doc_text)

    # Build paragraph index for complaints/declarations/answers
    paragraphs: Dict[int, str] = {}
    if doc_type in ("complaint", "declaration", "answer"):
        paragraphs = _extract_numbered_paragraphs(full_text)

    # Build line index for depositions/transcripts
    lines: Dict[str, str] = {}
    if doc_type in ("deposition", "transcript"):
        depo_pages, lines = _extract_deposition_lines(full_text)
        # Merge deposition pages into main page index if we got them
        if depo_pages:
            pages.update(depo_pages)

    return CorpusDocument(
        label=label,
        document_type=doc_type,
        file_path=str(path),
        full_text=full_text,
        pages=pages,
        paragraphs=paragraphs,
        lines=lines,
        page_count=len(pages),
        paragraph_count=len(paragraphs),
    )
