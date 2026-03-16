#!/usr/bin/env python3
"""Integration test for closed-corpus record citation verification.

Tests the full pipeline: extraction -> corpus indexing -> verification.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from legal_citation_checker.extractors import extract_docx_text
from legal_citation_checker.record_extractor import extract_record_citations
from legal_citation_checker.corpus_index import CorpusIndex
from legal_citation_checker.record_verifier import RecordVerifier


CORPUS_DIR = Path(__file__).resolve().parent / "test_documents" / "corpus"
BRIEF_PATH = CORPUS_DIR / "summary_judgment_brief.docx"


def test_record_extraction():
    """Test that we extract all record citations from the brief."""
    doc = extract_docx_text(BRIEF_PATH)
    citations = extract_record_citations(doc)

    print(f"\n{'=' * 70}")
    print(f"  RECORD CITATION EXTRACTION")
    print(f"{'=' * 70}")
    print(f"  Found {len(citations)} record citations\n")

    for i, c in enumerate(citations, 1):
        print(f"  [{i:2d}] {c.raw_text}")
        print(f"       type={c.document_type} label='{c.document_label}' "
              f"page={c.page_ref} line={c.line_ref} para={c.paragraph_ref}")
        if c.quoted_text:
            print(f"       quote: \"{c.quoted_text[:60]}...\"")
        print()

    # We expect at minimum these citation types
    types = {c.document_type for c in citations}
    assert "complaint" in types, f"Missing complaint citations, got types: {types}"
    assert "exhibit" in types, f"Missing exhibit citations, got types: {types}"
    assert "deposition" in types, f"Missing deposition citations, got types: {types}"
    assert "declaration" in types, f"Missing declaration citations, got types: {types}"

    return citations


def test_corpus_index():
    """Test that the corpus index correctly ingests all documents."""
    # Exclude the brief itself from the corpus
    corpus = CorpusIndex.from_directory(CORPUS_DIR)

    print(f"\n{'=' * 70}")
    print(f"  CORPUS INDEX")
    print(f"{'=' * 70}")
    print(f"  Indexed {len(corpus.documents)} documents\n")

    for doc in corpus.documents:
        print(f"  {doc.label} ({doc.document_type})")
        print(f"    file: {Path(doc.file_path).name}")
        print(f"    pages: {doc.page_count}, paragraphs: {doc.paragraph_count}")
        if doc.lines:
            print(f"    lines indexed: {len(doc.lines)}")
        print()

    # Verify we can find documents by label
    assert corpus.find_document("Complaint") is not None
    assert corpus.find_document("Exhibit A") is not None
    assert corpus.find_document("Exhibit B") is not None
    assert corpus.find_document("Ex. A") is not None  # abbreviation
    assert corpus.find_document("Smith Dep.") is not None  # deposition
    assert corpus.find_document("Johnson Declaration") is not None
    assert corpus.find_document("Exhibit F") is None  # doesn't exist

    # Verify paragraph access
    complaint = corpus.find_document("Complaint")
    assert complaint is not None
    assert complaint.paragraph_count > 0, f"No paragraphs extracted from Complaint"
    para6 = corpus.get_paragraph_text("Complaint", 6)
    assert para6 is not None, "Complaint ¶ 6 should exist"
    assert "January 15, 2024" in para6, f"Wrong text for ¶ 6: {para6[:100]}"

    return corpus


def test_full_verification(citations, corpus):
    """Test verification of record citations against corpus."""
    verifier = RecordVerifier(corpus)

    print(f"\n{'=' * 70}")
    print(f"  RECORD CITATION VERIFICATION")
    print(f"{'=' * 70}\n")

    results = []
    for c in citations:
        result = verifier.verify(c)
        results.append((c, result))

        icon = {
            "Verified": "✅",
            "Document Not Found": "🔴",
            "Location Mismatch": "⚠️ ",
            "Quote Mismatch": "🟡",
            "Needs Review": "❓",
        }.get(result.status, "?")

        print(f"  {icon} [{result.confidence:3d}%] {c.raw_text}")
        print(f"         {result.evidence[:120]}")
        if result.matched_text:
            print(f"         matched: \"{result.matched_text[:80]}...\"")
        if result.suggested_location:
            print(f"         suggestion: {result.suggested_location}")
        print()

    # Count results by status
    verified = [r for _, r in results if r.status == "Verified"]
    not_found = [r for _, r in results if r.status == "Document Not Found"]
    loc_mismatch = [r for _, r in results if r.status == "Location Mismatch"]
    quote_mismatch = [r for _, r in results if r.status == "Quote Mismatch"]

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total:            {len(results)}")
    print(f"  Verified:         {len(verified)}")
    print(f"  Document Not Found: {len(not_found)}")
    print(f"  Location Mismatch:  {len(loc_mismatch)}")
    print(f"  Quote Mismatch:     {len(quote_mismatch)}")

    # Assertions based on our ground truth
    assert len(not_found) >= 1, f"Should find at least 1 missing document (Exhibit F)"
    assert len(loc_mismatch) >= 1, f"Should find at least 1 location mismatch"

    print(f"\n  All assertions passed!")
    return results


def main():
    if not BRIEF_PATH.exists():
        print("Test documents not found. Run generate_corpus_test.py first.")
        return 1

    print("=" * 70)
    print("  CLOSED-CORPUS VERIFICATION INTEGRATION TEST")
    print("=" * 70)

    citations = test_record_extraction()
    corpus = test_corpus_index()

    # Filter out citations for the brief itself if the brief is in the corpus dir
    # (the brief gets indexed too since it's a .docx in the corpus dir)
    test_citations = citations  # all citations from the brief
    test_full_verification(test_citations, corpus)

    return 0


if __name__ == "__main__":
    sys.exit(main())
