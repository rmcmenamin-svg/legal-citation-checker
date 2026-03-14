# Legal Citation Checker

A citation authenticity verification tool that detects AI-hallucinated citations in legal documents. Checks citations against CourtListener's free legal database using a multi-tier search strategy designed for zero false negatives.

## Features

- **DOCX and PDF support** — Extract citations from Word documents and PDFs
- **eyecite integration** — Recognizes 55+ million citation patterns
- **Bluebook normalization** — Standardizes citations using reporters-db
- **Tiered verification** — Multiple CourtListener search strategies before flagging
- **Hallucination detection** — Flags fabricated citations with confidence scores
- **Audit reports** — Export results as Markdown, HTML, or JSON

## Installation

```bash
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install -e .
```

## Usage

### Command Line

```bash
# Basic usage — prints Markdown report to stdout
citecheck document.docx

# Save report to file
citecheck document.docx -o report.md

# JSON output
citecheck document.docx -f json -o report.json

# HTML output with verbose logging
citecheck document.docx -f html -o report.html -v

# Custom API timeout
citecheck document.docx --timeout 15

# Disable caching (re-verify duplicate citations)
citecheck document.docx --no-cache
```

### Python API

```python
from legal_citation_checker import CitationChecker

checker = CitationChecker(verbose=True)
report = checker.process_document("brief.docx")

# Print summary
print(f"Total: {report.total_citations}")
print(f"Verified: {report.verified_count}")
print(f"Potential hallucinations: {report.hallucination_count}")
print(f"Needs review: {report.needs_review_count}")

# Export
report.save("audit.md", format="markdown")
report.save("audit.json", format="json")
```

## Verification Pipeline

Citations go through a tiered verification process:

1. **CourtListener exact match** — Search by citation string (95% confidence)
2. **CourtListener alternate queries** — Quoted citation, name+citation, reporter triplet (90% confidence)
3. **CourtListener relaxed search** — Triplet+year filter, case name+year (80-85% confidence)
4. **Network error handling** — All-error results flagged as "Needs Review" (not hallucination)
5. **Hallucination declaration** — Only after multiple real "not found" responses

### Citation Statuses

| Status | Meaning |
|--------|---------|
| Verified (CourtListener) | Citation found in CourtListener database |
| Potential Hallucination | Citation not found after exhaustive search |
| Needs Review | Could not verify (network errors, Westlaw citations, etc.) |
| Skipped (Non-Case Citation) | Statute, regulation, or non-verifiable citation type |

## Project Structure

```
src/legal_citation_checker/
├── __init__.py          # Package exports
├── __main__.py          # Entry point
├── cli.py               # Command-line interface
├── pipeline.py          # Pipeline orchestrator
├── models.py            # Data classes
├── extractors.py        # DOCX/PDF text and citation extraction
├── normalizer.py        # Bluebook normalization
├── verifier.py          # CourtListener verification logic
└── report.py            # Audit report generation
```

## Dependencies

- **eyecite** — Citation extraction
- **reporters-db** — Reporter database for normalization
- **python-docx** — DOCX file processing
- **pdfplumber** — PDF file processing
- **requests** — HTTP client for CourtListener API

## License

MIT
