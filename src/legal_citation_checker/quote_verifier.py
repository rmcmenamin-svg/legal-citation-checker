"""Verify quoted text against opinion text from CourtListener.

After a citation is verified to exist, this module checks whether
quoted text attributed to the citation actually appears in the opinion.

Strategy:
1. Extract opinion ID from the CourtListener source URL.
2. Fetch opinion text via the CourtListener API (needs API token)
   or fall back to fetching the public HTML opinion page.
3. Fuzzy-match the quoted text against the opinion text.

This catches a common LLM hallucination pattern: real citation,
fabricated quote.
"""

from __future__ import annotations

import difflib
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("legal_citation_checker")

# Minimum similarity for a quote to be considered verified.
QUOTE_VERIFY_THRESHOLD = 0.80
QUOTE_VERIFY_GOOD = 0.90

# CourtListener API base for opinion detail.
_CL_OPINION_API = "https://www.courtlistener.com/api/rest/v4/opinions/{}/"
_CL_CLUSTER_API = "https://www.courtlistener.com/api/rest/v4/clusters/{}/"

# Regex to extract opinion ID from CourtListener URLs.
# Matches: /opinion/12345/case-name/ or /api/rest/v4/opinions/12345/
_OPINION_ID_RE = re.compile(r"/opinion(?:s)?/(\d+)/")
_CLUSTER_ID_RE = re.compile(r"/clusters?/(\d+)/")


class _HTMLTextExtractor(HTMLParser):
    """Extract visible text from HTML, stripping tags."""

    def __init__(self):
        super().__init__()
        self._parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = False
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2014", "--").replace("\u2013", "-")
    return " ".join(text.split())


def _fuzzy_quote_match(
    needle: str, haystack: str, threshold: float = QUOTE_VERIFY_THRESHOLD
) -> Tuple[bool, float, Optional[str]]:
    """Check if `needle` appears in `haystack` with fuzzy matching.

    Returns (matched, similarity, best_match_text).
    """
    if not needle or not haystack:
        return (False, 0.0, None)

    needle_norm = _normalize_for_comparison(needle.lower())
    haystack_norm = _normalize_for_comparison(haystack.lower())

    # Exact substring check
    if needle_norm in haystack_norm:
        return (True, 1.0, needle)

    # Sliding window fuzzy match
    needle_len = len(needle_norm)
    best_ratio = 0.0
    best_text = None

    if len(haystack_norm) < needle_len:
        ratio = difflib.SequenceMatcher(None, needle_norm, haystack_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_text = haystack
    else:
        step = max(1, needle_len // 8)
        for i in range(0, len(haystack_norm) - needle_len + 1, step):
            # Try multiple window sizes around needle length
            for extra in (0, 10, 20):
                window = haystack_norm[i: i + needle_len + extra]
                ratio = difflib.SequenceMatcher(None, needle_norm, window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_text = haystack[i: i + needle_len + extra].strip()

    return (best_ratio >= threshold, best_ratio, best_text)


def extract_opinion_id(url: str) -> Optional[str]:
    """Extract the CourtListener opinion ID from a URL."""
    if not url:
        return None
    m = _OPINION_ID_RE.search(url)
    return m.group(1) if m else None


def extract_cluster_id(url: str) -> Optional[str]:
    """Extract the CourtListener cluster ID from a URL."""
    if not url:
        return None
    m = _CLUSTER_ID_RE.search(url)
    return m.group(1) if m else None


class QuoteVerifier:
    """Verify quoted text against CourtListener opinion text.

    Usage:
        qv = QuoteVerifier(session, timeout=8.0)
        result = qv.verify_quote(
            quote_text="the right of the people",
            source_url="https://www.courtlistener.com/opinion/12345/...",
        )
    """

    def __init__(
        self,
        session: Any = None,
        request_timeout: float = 8.0,
        api_token: Optional[str] = None,
    ):
        self._session = session
        self._timeout = request_timeout
        self._api_token = api_token
        # Cache opinion text by opinion ID to avoid refetching.
        self._opinion_cache: Dict[str, Optional[str]] = {}

    def verify_quote(
        self,
        quote_text: str,
        source_url: Optional[str],
        citation_text: str = "",
    ) -> "QuoteVerificationResult":
        """Verify a quoted passage against the opinion text.

        Args:
            quote_text: The quoted text from the brief.
            source_url: The CourtListener URL from verification.
            citation_text: The citation string (for logging/evidence).

        Returns:
            QuoteVerificationResult with status and details.
        """
        if not quote_text or len(quote_text.strip()) < 10:
            return QuoteVerificationResult(
                status="skipped",
                confidence=0,
                evidence="Quote too short to verify.",
            )

        if not source_url:
            return QuoteVerificationResult(
                status="no_source",
                confidence=0,
                evidence="No source URL available for quote verification.",
            )

        # Fetch opinion text
        opinion_text = self._get_opinion_text(source_url)
        if not opinion_text:
            return QuoteVerificationResult(
                status="text_unavailable",
                confidence=0,
                evidence=(
                    "Could not retrieve opinion text from CourtListener. "
                    "Quote verification requires access to the full opinion."
                ),
            )

        # Fuzzy match the quote against the opinion text
        matched, similarity, match_text = _fuzzy_quote_match(quote_text, opinion_text)

        if matched:
            conf = 95 if similarity >= QUOTE_VERIFY_GOOD else 80
            return QuoteVerificationResult(
                status="verified",
                confidence=conf,
                evidence=(
                    f"Quote found in opinion text (similarity: {similarity:.0%})."
                ),
                matched_text=match_text,
                similarity=similarity,
            )

        # Not matched — potential fabricated quote
        return QuoteVerificationResult(
            status="not_found",
            confidence=85,
            evidence=(
                f"Quote not found in opinion text "
                f"(best similarity: {similarity:.0%}). "
                f"The quoted passage may be fabricated or paraphrased."
            ),
            similarity=similarity,
        )

    def _get_opinion_text(self, source_url: str) -> Optional[str]:
        """Fetch the full opinion text from CourtListener.

        Tries in order:
        1. API endpoint with auth token (if available)
        2. Public HTML opinion page
        """
        opinion_id = extract_opinion_id(source_url)
        if not opinion_id:
            return None

        # Check cache
        if opinion_id in self._opinion_cache:
            return self._opinion_cache[opinion_id]

        text = None

        # Strategy 1: CourtListener API (needs token)
        if self._api_token:
            text = self._fetch_via_api(opinion_id)

        # Strategy 2: Public HTML page
        if not text:
            text = self._fetch_via_html(source_url)

        self._opinion_cache[opinion_id] = text
        return text

    def _fetch_via_api(self, opinion_id: str) -> Optional[str]:
        """Fetch opinion text via the CourtListener REST API."""
        if not self._session:
            return None

        url = _CL_OPINION_API.format(opinion_id)
        headers = {}
        if self._api_token:
            headers["Authorization"] = f"Token {self._api_token}"

        try:
            resp = self._session.get(
                url, headers=headers, timeout=self._timeout
            )
            if resp.status_code >= 400:
                logger.debug(
                    "CourtListener API %s returned %d", url, resp.status_code
                )
                return None

            try:
                data = resp.json()
            except Exception:
                return None
            # Try plain_text first, then html_with_citations, then html
            for field in ("plain_text", "html_with_citations", "html"):
                text = data.get(field, "")
                if isinstance(text, str) and len(text) > 50:
                    if field.startswith("html"):
                        text = self._html_to_text(text)
                    return text

        except Exception as exc:
            logger.debug("CourtListener API fetch failed: %s", exc)

        return None

    def _fetch_via_html(self, source_url: str) -> Optional[str]:
        """Fetch opinion text by scraping the public opinion page."""
        if not self._session:
            return None

        try:
            resp = self._session.get(source_url, timeout=self._timeout)
            if resp.status_code >= 400:
                logger.debug(
                    "CourtListener HTML %s returned %d",
                    source_url,
                    resp.status_code,
                )
                return None

            html = resp.text
            # Extract opinion text from the page.
            # CourtListener puts opinion text in <div id="opinion-content">
            # or similar containers.
            text = self._extract_opinion_from_html(html)
            if text and len(text) > 100:
                return text

        except Exception as exc:
            logger.debug("CourtListener HTML fetch failed: %s", exc)

        return None

    def _extract_opinion_from_html(self, html: str) -> Optional[str]:
        """Extract opinion text from CourtListener's HTML page.

        Looks for the opinion content within known container elements,
        then falls back to full-page text extraction.
        """
        # Try to find the opinion content section
        # CourtListener uses various containers — try common patterns
        for pattern in (
            r'<div[^>]*id=["\']opinion-content["\'][^>]*>(.*?)</div>',
            r'<article[^>]*class="[^"]*opinion[^"]*"[^>]*>(.*?)</article>',
            r'<pre[^>]*class="[^"]*plaintext[^"]*"[^>]*>(.*?)</pre>',
            r'<div[^>]*class="[^"]*opinion-text[^"]*"[^>]*>(.*?)</div>',
        ):
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                text = self._html_to_text(match.group(1))
                if text and len(text.strip()) > 20:
                    return text

        # Fall back to extracting all text from the page body
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        if body_match:
            text = self._html_to_text(body_match.group(1))
            # Only use if we got substantial text
            if len(text) > 500:
                return text

        return None

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text."""
        extractor = _HTMLTextExtractor()
        try:
            extractor.feed(html)
        except Exception:
            # Fallback: strip tags with regex
            text = re.sub(r"<[^>]+>", " ", html)
            return " ".join(text.split())
        return extractor.get_text().strip()


class QuoteVerificationResult:
    """Result of verifying a quote against opinion text."""

    def __init__(
        self,
        status: str,
        confidence: int = 0,
        evidence: str = "",
        matched_text: Optional[str] = None,
        similarity: Optional[float] = None,
    ):
        self.status = status          # verified, not_found, skipped, no_source, text_unavailable
        self.confidence = confidence
        self.evidence = evidence
        self.matched_text = matched_text
        self.similarity = similarity

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": self.status,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }
        if self.matched_text:
            d["matched_text"] = self.matched_text
        if self.similarity is not None:
            d["similarity"] = round(self.similarity, 3)
        return d
