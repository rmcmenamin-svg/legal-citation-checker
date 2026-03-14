# Legal Citation Checker - Phase 1: DETAILED TECHNICAL SPECIFICATION

## CRITICAL: DO NOT START CODING UNTIL THIS SPEC IS REVIEWED

## 1. Project Scope & Boundaries

### IN SCOPE (Phase 1 ONLY):
- ✅ Citation authenticity verification
- ✅ DOCX file input only
- ✅ Zero false negatives requirement
- ✅ Exhaustive search before declaring hallucination
- ✅ Audit report generation (markdown/html/json)

### OUT OF SCOPE (Phase 1):
- ❌ Quote verification
- ❌ PDF support
- ❌ Citation accuracy/typo detection
- ❌ Legal analysis
- ❌ Batch processing
- ❌ Web interface

## 2. Core Requirements (Non-Negotiable)

### 2.1 Zero False Negatives
- **Legal ethics requirement**: Must NEVER miss a real citation
- **Implementation**: Minimum 3 independent search strategies per citation
- **Fallback chain**: CourtListener → Google Caselaw → Secondary sources → Manual review flag
- **Confidence threshold**: 95%+ before declaring "verified"

### 2.2 Performance Requirements
- **Processing time**: <30 seconds for typical 50-page legal brief
- **Memory usage**: <500MB peak
- **Network timeouts**: 8 seconds per API call
- **Cache strategy**: 1-hour TTL for successful verifications

### 2.3 Accuracy Requirements
- **Hallucination detection**: 95%+ accuracy on fabricated citations
- **False positive rate**: <5% acceptable (better to flag uncertain than miss)
- **Citation extraction**: 98%+ recall using eyecite

## 3. Technical Architecture

### 3.1 File Structure (MUST FOLLOW)
```
legal-citation-checker/
├── src/legal_citation_checker/
│   ├── __init__.py
│   ├── cli.py                    # CLI interface ONLY
│   ├── pipeline.py               # Main orchestration
│   ├── docx_processor.py         # DOCX text extraction
│   ├── citation_extractor.py     # eyecite integration
│   ├── normalizer.py             # Bluebook normalization
│   ├── verifier.py               # Verification pipeline
│   ├── search_strategies.py      # Search algorithms
│   ├── report_generator.py       # Audit reports
│   └── models.py                 # Data classes
├── tests/
│   ├── test_documents/           # Test DOCX files
│   ├── conftest.py
│   ├── test_docx_processor.py
│   ├── test_citation_extractor.py
│   ├── test_normalizer.py
│   ├── test_verifier.py
│   └── test_integration.py
├── examples/
│   ├── sample_brief.docx         # Example with real citations
│   ├── sample_hallucinated.docx  # Example with fake citations
│   └── expected_report.md        # Expected output
├── requirements.txt
├── setup.py
├── pyproject.toml
├── README.md
└── TASK.md
```

### 3.2 Dependencies (EXACT VERSIONS)
```txt
# Core dependencies
python-docx==1.1.0
eyecite==2.5.0
reporters-db==3.2.32
requests==2.31.0

# Development
pytest==8.0.0
black==24.0.0
mypy==1.8.0
pytest-asyncio==0.23.0

# Optional (for fallback)
beautifulsoup4==4.12.0
lxml==4.9.0
```

## 4. API Contracts (MUST IMPLEMENT)

### 4.1 CitationChecker Class
```python
class CitationChecker:
    def __init__(
        self,
        verbose: bool = False,
        request_timeout: float = 8.0,
        cache_ttl: int = 3600,
        user_agent: str = "legal-citation-checker/0.1.0"
    ) -> None:
        """
        Initialize the citation checker.
        
        Args:
            verbose: Enable debug logging
            request_timeout: HTTP timeout in seconds
            cache_ttl: Cache TTL in seconds
            user_agent: User-Agent header for API requests
        """
        
    def process_document(
        self,
        input_file: Path | str,
        output_format: Literal["markdown", "html", "json"] = "markdown"
    ) -> AuditReport:
        """
        Process a DOCX file and return an audit report.
        
        Args:
            input_file: Path to DOCX file
            output_format: Format for the report
            
        Returns:
            AuditReport object
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is not DOCX
            RuntimeError: If dependencies missing
            requests.exceptions.RequestException: On network errors
        """
        
    def verify_citation(
        self,
        citation_text: str,
        context: str = "",
        metadata: Dict[str, Any] | None = None
    ) -> VerificationResult:
        """
        Verify a single citation.
        
        Args:
            citation_text: Raw citation text
            context: Surrounding text (for error messages)
            metadata: Optional citation metadata
            
        Returns:
            VerificationResult with status, confidence, evidence
        """
```

### 4.2 AuditReport Class
```python
@dataclass
class AuditReport:
    """Immutable audit report."""
    
    # Metadata
    document_path: Path
    processed_at: datetime
    processing_time_seconds: float
    
    # Statistics
    total_citations: int
    verified_citations: int
    uncertain_citations: int
    hallucination_candidates: int
    
    # Results
    citations: List[CitationResult]
    summary: str
    recommendations: List[str]
    
    # Methods
    def to_markdown(self) -> str:
        """Generate markdown report."""
        
    def to_html(self) -> str:
        """Generate HTML report."""
        
    def to_json(self) -> str:
        """Generate JSON report."""
        
    def save(self, output_path: Path, format: str = "markdown") -> None:
        """Save report to file."""
        
    def print_summary(self) -> None:
        """Print human-readable summary to stdout."""
```

### 4.3 VerificationResult Class
```python
@dataclass
class VerificationResult:
    """Result of verifying a single citation."""
    
    # Core fields
    citation_text: str
    normalized_citation: str
    status: Literal["verified", "uncertain", "hallucination", "error"]
    confidence: int  # 0-100
    
    # Evidence
    source: Optional[str]  # "CourtListener", "GoogleCaselaw", etc.
    source_url: Optional[str]
    evidence: str  # Human-readable evidence
    
    # Search details
    search_attempts: List[SearchAttempt]
    total_search_time: float
    
    # Metadata
    context: str
    paragraph_index: Optional[int]
    citation_type: str  # "case", "statute", "journal", etc.
    
    # Methods
    def is_verified(self) -> bool:
        return self.status == "verified" and self.confidence >= 95
        
    def is_hallucination(self) -> bool:
        return self.status == "hallucination" and self.confidence >= 90
        
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
```

## 5. Verification Pipeline (EXACT ALGORITHM)

### 5.1 Step 1: Citation Extraction
```python
def extract_citations(text: str) -> List[RawCitation]:
    """
    Extract citations using eyecite.
    
    Algorithm:
    1. Use eyecite.get_citations() with cleanup=True
    2. Filter to only case citations (skip statutes, journals for now)
    3. Extract metadata: reporter, volume, page, year, parties
    4. Capture context (100 chars before/after)
    5. Record character offsets for debugging
    
    Returns:
        List of RawCitation objects
    """
```

### 5.2 Step 2: Bluebook Normalization
```python
def normalize_to_bluebook(citation: RawCitation) -> NormalizedCitation:
    """
    Normalize citation to Bluebook format.
    
    Algorithm:
    1. Use reporters-db to canonicalize reporter abbreviation
    2. Apply Bluebook 21st Edition rules:
       - Volume number: Arabic numerals
       - Reporter: Standard abbreviation
       - Page number: Arabic numerals
       - Year: Parentheses, full 4-digit year
       - Court abbreviation if present
    3. Handle common variations:
       - "Cal. App. 4th" → "Cal. App. 4th"
       - "F.3d" → "F.3d"
       - "U.S." → "U.S."
    
    Returns:
        NormalizedCitation with original and normalized text
    """
```

### 5.3 Step 3: Tiered Verification

#### 3.1 CourtListener API (Primary)
```python
def verify_courtlistener(citation: NormalizedCitation) -> Optional[VerificationResult]:
    """
    Verify citation using CourtListener API.
    
    Search strategies (in order):
    1. Exact citation match: /api/rest/v4/opinions/?citation=...
    2. Citation without periods: Remove all periods from citation
    3. Broad search: /api/rest/v4/search/?q=...
    
    Success criteria:
    - Exact match on normalized citation
    - OR match on reporter+volume+page with same year (±1)
    - OR match on case name with same court and year
    
    Timeout: 8 seconds total
    """
```

#### 3.2 Google Caselaw Fallback
```python
def verify_google_caselaw(citation: NormalizedCitation) -> Optional[VerificationResult]:
    """
    Verify citation using Google Caselaw.
    
    Search strategies (in order):
    1. Full case name + court + year
    2. Parties + reporter + page
    3. Normalized citation only
    
    Implementation:
    - Use gcl library if available
    - Fallback to web scraping if gcl not installed
    - Parse Google Scholar results
    
    Success criteria:
    - Citation appears in search results
    - Case details match metadata
    
    Timeout: 10 seconds total
    """
```

#### 3.3 Secondary Sources
```python
def verify_secondary_sources(citation: NormalizedCitation) -> Optional[VerificationResult]:
    """
    Try secondary legal databases.
    
    Sources to try:
    1. Caselaw Access Project (CAP) API
    2. Harvard Law Library API
    3. Free Law Project APIs
    
    Success criteria:
    - Any match in reputable legal database
    
    Timeout: 5 seconds per source
    """
```

### 5.4 Step 4: Hallucination Decision
```python
def decide_hallucination(
    citation: NormalizedCitation,
    attempts: List[SearchAttempt]
) -> VerificationResult:
    """
    Determine if citation is hallucinated.
    
    Decision logic:
    - If 0 successful searches AND ≥3 attempts → hallucination (90% confidence)
    - If 0 successful searches AND <3 attempts → uncertain (50% confidence)
    - If partial matches (wrong year/court) → uncertain (70% confidence)
    
    Evidence must include:
    - List of all search attempts
    - URLs queried
    - Error messages if any
    - Total search time
    """
```

## 6. Error Handling Requirements

### 6.1 Recoverable Errors (MUST HANDLE)
- Network timeouts → retry once, then continue
- API rate limits → exponential backoff
- Malformed citations → skip with warning
- Missing dependencies → clear error message

### 6.2 Fatal Errors (MUST RAISE)
- File not found → FileNotFoundError
- Invalid file type → ValueError
- Missing required dependencies → RuntimeError
- Permission denied → PermissionError

### 6.3 Logging Requirements
- INFO: Document processing started/completed
- WARNING: Skipped citations, network issues
- ERROR: Fatal errors only
- DEBUG: Search details (only if verbose=True)

## 7. Test Requirements

### 7.1 Unit Tests (100% coverage required)
```python
# test_docx_processor.py
def test_extract_text_preserves_structure()
def test_handle_docx_formatting_issues()
def test_error_on_non_docx_file()

# test_citation_extractor.py  
def test_extract_case_citations()
def test_skip_statute_citations()
def test_capture_context()

# test_normalizer.py
def test_bluebook_normalization()
def test_reporter_canonicalization()
def test_handle_variations()

# test_verifier.py
def test_courtlistener_exact_match()
def test_google_caselaw_fallback()
def test_hallucination_decision_logic()
```

### 7.2 Integration Tests
```python
# test_integration.py
def test_end_to_end_real_document()
def test_end_to_end_hallucinated_document()
def test_performance_under_30_seconds()
def test_zero_false_negatives()
```

### 7.3 Test Data
- `tests/test_documents/real_brief.docx` - Actual legal brief with 20+ citations
- `tests/test_documents/hallucinated.docx` - Document with fabricated citations
- `tests/test_documents/mixed.docx` - Mix of real and fake citations

## 8. CLI Interface Specification

### 8.1 Command Structure
```bash
# Basic usage
legal-citation-checker document.docx

# With options
legal-citation-checker document.docx \
  --output report.md \
  --format markdown \
  --verbose

# Help
legal-citation-checker --help
```

### 8.2 Arguments
```
positional arguments:
  input_file            DOCX file to check

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output file (default: stdout)
  -f {markdown,html,json}, --format {markdown,html,json}
                        Output format (default: markdown)
  -v, --verbose         Enable verbose output
  --timeout TIMEOUT     API timeout in seconds (default: 8)
  --no-cache            Disable response caching
  --version             Show version and exit
```

### 8.3 Exit Codes
- `0`: Success
- `1`: File error (not found, not DOCX)
- `2`: Dependency error
- `3`: Network error
- `4`: Internal error

## 9. Performance Requirements

### 9.1 Time Budget (30 seconds total)
- DOCX extraction: 2 seconds
- Citation extraction: 3 seconds  
- Normalization: 1 second
- Verification (per citation): 1 second
- Report generation: 2 seconds
- **Buffer**: 21 seconds for network/retries

### 9.2 Memory Budget
- Base: 50MB
- Per document: +10MB per 100 pages
- Cache: +5MB per 100 cached citations
- **Max**: 500MB

### 9.3 Network Budget
- CourtListener: 3 requests per citation max
- Google Caselaw: 2 requests per citation max
- Secondary: 1 request per citation max
- **Total**: 6 requests per citation max

## 10. Quality Gates (MUST PASS BEFORE RELEASE)

### 10.1 Code Quality
- [ ] 100% test coverage on core modules
- [ ] 0 linting errors (black, mypy)
- [ ] All type hints correct
- [ ] Documentation complete

### 10.2 Functional Tests
- [ ] Zero false negatives on test suite
- [ ] <30 second processing time
- [ ] Correct hallucination detection (≥95%)
- [ ] All output formats work

### 10.3 Integration Tests
- [ ] Works with real legal documents
- [ ] Handles network failures gracefully
- [ ] Cache works correctly
- [ ] CLI interface complete

## 11. Timeline & Next Steps

### Current Date: March 14, 2026

### BEFORE CODING (March 14-15):
1. [ ] Review this specification (March 14)
2. [ ] Add missing details (March 14)
3. [ ] Define exact test cases (March 14)
4. [ ] Create sample documents (March 15)
5. [ ] Final spec approval (March 15)

### CODING PHASES:
**Phase A (March 16-18)**: Core infrastructure (3 days)
- DOCX processor
- Citation extractor  
- Basic data models
- Test framework

**Phase B (March 19-21)**: Verification engine (3 days)
- CourtListener integration
- Google Caselaw fallback
- Search strategies
- Cache implementation

**Phase C (March 22-24)**: Reporting & polish (3 days)
- Audit report generator
- CLI interface
- Performance optimization
- Error handling

**Phase D (March 25-27)**: Testing & release (3 days)
- Comprehensive testing
- Performance benchmarking
- Documentation
- Release preparation

**Target Completion: March 27, 2026**

---

## REVIEW CHECKLIST

- [ ] Are all requirements captured?
- [ ] Are APIs clearly defined?
- [ ] Are error cases handled?
- [ ] Are performance requirements realistic?
- [ ] Are test requirements sufficient?
- [ ] Are dependencies correctly specified?
- [ ] Is the scope properly bounded?

**DO NOT START CODING UNTIL THIS CHECKLIST IS COMPLETE**
