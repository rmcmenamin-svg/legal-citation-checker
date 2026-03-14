# Task: Legal Citation Checker - Phase 1 (Citation Authenticity Only)

## Project Overview
Build a foolproof legal citation verification tool that detects AI hallucinations in legal documents. **Phase 1 focuses exclusively on citation authenticity verification.** No quote verification, no other features. Focus on DOCX files only (no PDF support).

## Core Requirements

### Primary Goal:
**Verify citation existence** - Detect fabricated/hallucinated citations with exhaustive search.

### Critical Constraints:
1. **Zero false negatives** - Must not miss real citations (legal ethics requirement)
2. **Sub-30-second processing** per typical legal document
3. **Exhaustive verification** before declaring hallucination
4. **DOCX-only input** for Phase 1

### Phase 1 Scope (Only):
- Extract citations from DOCX documents
- Normalize to Bluebook format
- Verify existence through tiered search pipeline
- Generate audit report with verification evidence
- **NO quote verification**
- **NO PDF support**
- **NO other features**

## Technical Architecture

### Core Libraries (Mandatory):
1. **`eyecite`** (freelawproject/eyecite) - Primary citation extractor
   - Recognizes 55+ million citation patterns
   - Used by CourtListener and Harvard Caselaw Access Project
   - Handles: full cases, statutes, law journals, supra, id.

2. **`reporters-db`** (freelawproject/reporters-db) - Reporter database
   - Database of 1,167 reporters + 2,102 name variations
   - Bluebook abbreviations and variations

3. **`bluebook-cite`** (delschlangen/bluebook-cite) - Citation formatting
   - Bluebook 21st Edition rules
   - Completes incomplete citations using free legal databases

4. **`gcl`** (Altabeh/gcl) - Google Caselaw parser
   - Scrapes/parses Google Caselaw pages
   - Extracts full case info, judges, dates

5. **`python-docx`** - DOCX file processing
   - Extract text with paragraph/sentence structure preserved
   - Maintain context for quote verification

### Verification Sources:
- **Primary**: CourtListener API (free, no keys required)
- **Fallback**: Google Caselaw via `gcl`
- **Format validation**: `bluebook-cite` for Bluebook compliance

## Phase 1 Features (Citation Authenticity Verification Only)

### 1. DOCX Processing Module
- Extract text from DOCX files preserving structure
- Maintain paragraph/sentence boundaries for context
- Handle common DOCX formatting issues

### 2. Citation Extraction Pipeline
- Use `eyecite` for comprehensive citation finding
- Parse citations with full metadata (type, jurisdiction, year, etc.)
- **Output**: Raw extracted citations with context

### 3. Bluebook Formatting & Normalization
- Use `bluebook-cite` to make citations Bluebook compliant
- Normalize variations (e.g., "Cal." vs "Cal", "§" vs "section")
- **Output**: Standardized citations ready for verification

### 4. Tiered Verification Pipeline

#### **Step 1: CourtListener API (Primary)**
- Query CourtListener with Bluebook-compliant citation
- Check for exact matches
- **If match found**: Mark as "Verified (CourtListener)" with confidence 95%

#### **Step 2: Google Caselaw Search (Fallback)**
- **Only if CourtListener fails**
- Use `gcl` to search Google Caselaw
- **Complex search strategy**:
  1. Search with full case name + court + year
  2. Search with parties + reporter + page
  3. Search with normalized citation only
- **If match found**: Mark as "Verified (Google Caselaw)" with confidence 85%

#### **Step 3: Additional Database Fallbacks**
- **Only if both previous steps fail**
- Try other free legal databases
- Broader search with relaxed parameters
- **If match found**: Mark as "Verified (Secondary Source)" with confidence 70%

#### **Step 4: Hallucination Declaration**
- **Only after all verification attempts fail**
- Must have high confidence (multiple failed searches)
- Mark as "Potential Hallucination" with confidence score
- Include evidence of search attempts

### 5. Confidence-Based Reporting
- **High confidence verified**: Multiple sources agree
- **Medium confidence verified**: Single reliable source
- **Low confidence**: Partial matches or ambiguous results
- **Potential hallucination**: No matches after exhaustive search

### 6. Audit Report Generation
- Summary: "X citations found, Y verified, Z potential hallucinations"
- **Per-citation breakdown**:
  - Citation 1: `Brown v. Board, 347 U.S. 483 (1954)`
    - Status: **Verified (CourtListener)**
    - Confidence: 95%
    - Source: https://www.courtlistener.com/...
    - Bluebook normalized: Yes
  - Citation 2: `Smith v. Jones, 123 Cal. App. 4th 456 (2004)`
    - Status: **Verified (Google Caselaw)**
    - Confidence: 85%
    - Source: https://scholar.google.com/...
    - Search attempts: 3 (parties+court, citation only, relaxed)
  - Citation 3: `Fake v. Case, 999 F.3d 999 (2025)`
    - Status: **Potential Hallucination**
    - Confidence: 90%
    - Evidence: No matches in CourtListener, Google Caselaw, or secondary sources
    - Search attempts: 5 across multiple databases
- Export formats: Markdown, HTML, JSON

## Success Metrics

### Quantitative:
- **Accuracy**: 95%+ on hallucination detection
- **Processing time**: <30 seconds per 50-page document
- **False negative rate**: 0% (critical)
- **Exhaustive search requirement**: Minimum 3 search strategies per citation

### Qualitative:
- Clear, actionable audit reports
- Easy-to-understand confidence scores
- Clickable links to verified sources
- Professional output suitable for legal workflow

## Implementation Steps

### Week 1: Foundation
1. Set up Python environment with all required libraries
2. Build DOCX text extractor with context preservation
3. Implement basic `eyecite` integration for citation extraction
4. Create test suite with sample legal documents

### Week 2: Verification Core
1. Integrate CourtListener API for primary verification
2. Build tiered search pipeline with `gcl` fallback
3. Implement Bluebook normalization with `bluebook-cite`
4. Create complex Google search strategies (parties+court, citation-only, relaxed)

### Week 3: Reporting & Polish
1. Create audit report generator (Markdown/HTML/JSON)
2. Add confidence scoring system
3. Implement command-line interface
4. Performance optimization and error handling

### Week 4: Testing & Refinement
1. Test with real legal documents from practice
2. Validate against known hallucination examples
3. Performance benchmarking
4. Documentation and user guide

## File Structure
```
legal-citation-checker/
├── src/
│   ├── docx_processor.py      # DOCX text extraction
│   ├── citation_extractor.py  # eyecite integration
│   ├── verifier.py           # CourtListener + gcl verification
│   ├── search_strategies.py  # Complex Google search strategies
│   ├── report_generator.py   # Audit report creation
│   └── cli.py               # Command-line interface
├── tests/
│   ├── test_documents/      # Sample legal docs for testing
│   ├── test_extraction.py
│   ├── test_verification.py
│   └── test_quotes.py
├── requirements.txt
├── README.md
└── examples/
    └── sample_report.md     # Example audit report
```

## Testing Strategy

### Unit Tests:
- Citation extraction accuracy
- Quote extraction from context
- API response handling
- Format validation rules

### Integration Tests:
- End-to-end document processing
- CourtListener API integration
- Google Caselaw fallback
- Report generation

### Real-World Testing:
- Sample briefs from legal practice
- Known hallucination examples
- Edge cases and unusual citations
- Performance under load

## Constraints & Guidelines

### Critical Constraints:
- **Zero false negatives** - Must not miss real citations
- **Legal ethics compliance** - All findings must be evidence-based
- **No rate limiting issues** - Implement caching and batch processing
- **Clear audit trail** - Every finding must be traceable to source

### Code Quality:
- Type hints throughout
- Comprehensive error handling
- Logging for debugging
- Performance monitoring

### User Experience:
- Clear progress indicators during processing
- Human-readable error messages
- Export options for different workflows
- Configurable confidence thresholds

## Deliverables

### Code:
- Fully functional Python package
- Command-line interface
- Comprehensive test suite
- Example scripts and documentation

### Documentation:
- Installation and setup guide
- API documentation
- User guide with examples
- Troubleshooting guide

### Sample Output:
- Example audit reports
- Performance benchmarks
- Test results with known documents

## Future Phases (Not in Scope for Phase 1)

### Phase 2+ (Future):
- Quote accuracy verification
- PDF support
- Batch processing
- Integration with document editors
- Any other features

**Phase 1 is citation authenticity verification only.**

## Notes
- Start with simple, working features before adding complexity
- Focus on accuracy over speed in initial implementation
- Maintain clear separation between extraction, verification, and reporting
- All verification must be evidence-based with source citations

## Success Definition
A tool that legal professionals can trust to catch citation hallucinations and verify quote accuracy, with zero risk of missing real citations and clear evidence for every finding.