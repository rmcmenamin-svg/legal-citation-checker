"""Core citation checking pipeline orchestrator.

Delegates to specialized modules for extraction, normalization,
verification, and report generation.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime
    requests = None  # type: ignore

from .extractors import (
    SKIP_CITATION_TYPES,
    extract_citations,
    extract_docx_text,
    extract_pdf_text,
    is_statute_or_regulation,
)
from .models import (
    CitationAudit,
    DocumentText,
    ExtractedCitation,
    ParagraphSpan,
    SearchAttempt,
    VerificationDecision,
)
from .formatter import BluebookFormatter
from .normalizer import CitationNormalizer, canonical_text
from .report import AuditReport
from .verifier import (
    COURTLISTENER_SEARCH_BASE,
    CitationVerifier,
    _WESTLAW_PATTERN,
    case_name_from_metadata,
    reporter_triplet,
    strip_pincite,
    triplet_match,
)

logger = logging.getLogger("legal_citation_checker")

# Re-export for backward compatibility with existing imports.
_SKIP_CITATION_TYPES = SKIP_CITATION_TYPES
_WESTLAW_PATTERN = _WESTLAW_PATTERN


class CitationChecker:
    """Phase 1 pipeline orchestrator."""

    def __init__(
        self,
        verbose: bool = False,
        request_timeout: float = 8.0,
        user_agent: str = "legal-citation-checker/0.1",
        max_workers: int = 4,
        disable_cache: bool = False,
    ) -> None:
        self.verbose = verbose
        self.request_timeout = request_timeout
        self.user_agent = user_agent
        self.max_workers = max_workers
        self.disable_cache = disable_cache
        self.cache_ttl = 3600  # 1 hour in seconds
        self._verification_cache: Dict[str, Tuple[float, VerificationDecision]] = {}
        self._normalizer = CitationNormalizer()
        self._formatter = BluebookFormatter()

        if self.verbose and not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("[citation-checker] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)

        self._session = None
        if requests is not None:
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
            self._session = session

        self._verifier = CitationVerifier(self._session, self.request_timeout)

    def process_document(self, input_file: Path) -> AuditReport:
        """Run the complete pipeline and return a report object."""
        started = time.perf_counter()
        path = Path(input_file)

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".docx":
            self._log(f"Extracting DOCX text from {path}")
            document_text = extract_docx_text(path)
        elif suffix == ".pdf":
            self._log(f"Extracting PDF text from {path}")
            document_text = extract_pdf_text(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}. Supported: .docx, .pdf")

        self._log("Extracting citations with eyecite")
        extracted_citations = extract_citations(document_text, self._normalizer, self.verbose)

        self._log(f"Running verification pipeline for {len(extracted_citations)} citation(s)")

        # Build list of citations needing verification (check cache first).
        to_verify: List[Tuple[ExtractedCitation, str]] = []
        cached_decisions: Dict[int, VerificationDecision] = {}
        dedup_key_for: Dict[int, str] = {}  # citation.index -> cache_key (for dedup lookup)
        seen_keys: set = set()
        for citation in extracted_citations:
            base = strip_pincite(citation.normalized_citation or citation.raw_citation)
            cache_key = self._cache_key(base)
            dedup_key_for[citation.index] = cache_key
            if not self.disable_cache and cache_key in self._verification_cache:
                cached_at, cached_decision = self._verification_cache[cache_key]
                if (time.monotonic() - cached_at) > self.cache_ttl:
                    del self._verification_cache[cache_key]
                    self._log(f"Cache expired for citation {citation.index}")
                else:
                    cached_decisions[citation.index] = cached_decision.clone()
                self._log(f"Cache hit for citation {citation.index}: {citation.normalized_citation}")
            elif cache_key in seen_keys:
                self._log(f"Dedup: citation {citation.index} ({base}) already queued — will reuse result")
            else:
                seen_keys.add(cache_key)
                to_verify.append((citation, cache_key))

        # Verify uncached citations concurrently.
        verified_decisions: Dict[int, VerificationDecision] = {}
        if to_verify and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(to_verify))) as executor:
                future_map = {
                    executor.submit(self._verifier.verify, cit): (cit, key)
                    for cit, key in to_verify
                }
                for future in as_completed(future_map):
                    cit, key = future_map[future]
                    try:
                        decision = future.result(timeout=self.request_timeout * 3)
                    except Exception as exc:
                        decision = VerificationDecision(
                            status="Needs Review",
                            confidence=0,
                            evidence=f"Verification failed with error: {exc}",
                        )
                    self._verification_cache[key] = (time.monotonic(), decision.clone())
                    verified_decisions[cit.index] = decision
        else:
            for cit, key in to_verify:
                decision = self._verifier.verify(cit)
                self._verification_cache[key] = decision.clone()
                verified_decisions[cit.index] = decision

        # Assemble audit results in original order, deduplicating.
        audited_citations: List[CitationAudit] = []
        reported_keys: set = set()
        for citation in extracted_citations:
            ck = dedup_key_for[citation.index]
            if ck in reported_keys:
                continue  # skip duplicate citation
            reported_keys.add(ck)
            decision = cached_decisions.get(citation.index)
            if decision is None:
                decision = verified_decisions.get(citation.index)
            if decision is None:
                # Deduped citation — look up by cache key from verification cache
                if ck in self._verification_cache:
                    _, decision = self._verification_cache[ck]
                    decision = decision.clone()
                else:
                    decision = VerificationDecision(
                        status="Needs Review",
                        confidence=0,
                        evidence="Deduplication error: result not found.",
                    )
            bluebook = self._formatter.format(citation.parsed)
            audited_citations.append(
                CitationAudit(
                    index=citation.index,
                    raw_citation=citation.raw_citation,
                    normalized_citation=citation.normalized_citation,
                    citation_type=citation.citation_type,
                    context=citation.context,
                    paragraph_index=citation.paragraph_index,
                    metadata=citation.metadata,
                    bluebook_normalized=citation.bluebook_normalized,
                    status=decision.status,
                    confidence=decision.confidence,
                    source=decision.source,
                    source_url=decision.source_url,
                    evidence=decision.evidence,
                    search_attempts=decision.search_attempts,
                    bluebook_citation=bluebook,
                )
            )

        elapsed = time.perf_counter() - started
        notes: List[str] = []
        if not extracted_citations:
            notes.append("No citations detected by eyecite in document text.")
        if self._session is None:
            notes.append("requests is unavailable; online verification attempts cannot execute.")

        return AuditReport(
            source_document=str(path),
            generated_at=datetime.now(timezone.utc).isoformat(),
            processing_seconds=elapsed,
            citations=audited_citations,
            notes=notes,
        )

    # -- Backward-compatible static/instance methods used by tests --

    @staticmethod
    def _is_statute_or_regulation(citation_text: str) -> bool:
        return is_statute_or_regulation(citation_text)

    @staticmethod
    def _strip_pincite(citation: str) -> str:
        return strip_pincite(citation)

    @staticmethod
    def _raw_reporter_from_citation(citation: str) -> str:
        from .verifier import raw_reporter_from_citation
        return raw_reporter_from_citation(citation)

    def _normalize_bluebook(self, citation_text: str, metadata: Dict[str, Any]) -> Tuple[str, bool]:
        return self._normalizer.normalize(citation_text, metadata)

    def _verify_citation(self, citation: ExtractedCitation) -> VerificationDecision:
        return self._verifier.verify(citation)

    def _build_broad_query(self, citation: ExtractedCitation) -> str:
        from .verifier import _build_broad_query
        return _build_broad_query(citation)

    def _case_name_from_metadata(self, metadata: Dict[str, Any]) -> str:
        return case_name_from_metadata(metadata)

    def _cache_key(self, value: str) -> str:
        return canonical_text(value)

    def _canonical_text(self, value: str) -> str:
        return canonical_text(value)

    def _reporter_triplet(self, citation: str) -> Optional[Tuple[str, str, str]]:
        return reporter_triplet(citation)

    def _triplet_match(self, value: str, target: Tuple[str, str, str]) -> bool:
        return triplet_match(value, target)

    def _http_get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        return self._verifier._http_get_json(url, params=params)

    def _log(self, message: str) -> None:
        if self.verbose:
            logger.debug(message)
