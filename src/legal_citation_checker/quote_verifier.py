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
    # Strip California line-number artifacts: newline followed by 1-2 digits
    # e.g. "be\n11 notified" → "be notified"
    import re as _re
    text = _re.sub(r"\n\s*\d{1,2}\s+", " ", text)
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
        case_name: str = "",
        court: str = "",
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

        # Fetch opinion text — try CL first, then web search fallback
        opinion_text = self._get_opinion_text(source_url)
        if not opinion_text:
            opinion_text = self._get_opinion_text_via_web(citation_text, case_name, court)
        if not opinion_text:
            return QuoteVerificationResult(
                status="text_unavailable",
                confidence=0,
                evidence=(
                    "Could not retrieve opinion text from CourtListener or web search. "
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

        CL search result URLs use /opinion/CLUSTER_ID/ (cluster URLs).
        We must resolve the cluster to actual opinion IDs, then fetch text.

        Tries in order:
        1. Resolve cluster → opinion IDs → fetch via API (needs token)
        2. Public HTML opinion page (often JavaScript-rendered, limited)
        """
        cluster_id = extract_opinion_id(source_url)  # regex matches both /opinion/ and /opinions/
        if not cluster_id:
            return None

        cache_key = f"cluster:{cluster_id}"
        if cache_key in self._opinion_cache:
            return self._opinion_cache[cache_key]

        text = None

        # Strategy 1: Resolve cluster → opinion IDs, fetch each opinion's text
        if self._api_token and self._session:
            text = self._fetch_via_cluster(cluster_id)

        # Strategy 2: Public HTML page (fallback — often empty on JS-rendered pages)
        if not text:
            text = self._fetch_via_html(source_url)

        self._opinion_cache[cache_key] = text
        return text

    def _fetch_via_cluster(self, cluster_id: str) -> Optional[str]:
        """Resolve a cluster ID to sub-opinions and fetch text from the first available."""
        cluster_url = f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/"
        headers = {"Authorization": f"Token {self._api_token}"}
        try:
            resp = self._session.get(cluster_url, headers=headers, timeout=self._timeout)
            if resp.status_code >= 400:
                return None
            data = resp.json()
            sub_opinions = data.get("sub_opinions") or []
            for opinion_url in sub_opinions:
                # Extract opinion ID from URL like .../opinions/9889182/
                m = re.search(r"/opinions?/(\d+)/", opinion_url)
                if not m:
                    continue
                opinion_id = m.group(1)
                text = self._fetch_via_api(opinion_id)
                if text:
                    return text
        except Exception as exc:
            logger.debug("Cluster fetch failed for %s: %s", cluster_id, exc)
        return None

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

    def _get_opinion_text_via_web(
        self, citation_text: str, case_name: str = "", court: str = ""
    ) -> Optional[str]:
        """Search Brave for the case using multiple query strategies and fetch opinion text."""
        import os
        api_key = os.environ.get("BRAVE_API_KEY")
        if not api_key or not self._session:
            return None

        # Build 2-3 query variations using loose terms (no exact phrase quoting
        # on case names — abbreviations like "Hosp." "Corp." vary across sources).
        queries: List[str] = []
        # Strip entity suffixes and punctuation to get bare party tokens
        _noise = re.compile(r"\b(inc|corp|co|llc|llp|ltd|lp|hosp|indus|mfg|assoc|ass'n|dep't|dept)\b\.?", re.IGNORECASE)
        bare_name = _noise.sub("", case_name).replace("v.", "").replace(",", "").strip() if case_name else ""
        bare_name = " ".join(bare_name.split())  # collapse whitespace

        if bare_name and court:
            queries.append(f'{bare_name} AND {court} AND opinion')
        if bare_name and citation_text:
            queries.append(f'{bare_name} AND {citation_text}')
        if citation_text:
            queries.append(f'"{citation_text}" AND opinion text')

        preferred_domains = ("courtlistener.com", "scholar.google", "justia.com", "casetext.com", "law.justia.com", "leagle.com")

        for query in queries:
            try:
                resp = self._session.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": 5},
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    timeout=self._timeout,
                )
                if resp.status_code != 200:
                    continue
                results = resp.json().get("web", {}).get("results", [])
                for r in results:
                    url = r.get("url", "")
                    if any(d in url for d in preferred_domains):
                        text = self._fetch_via_html(url)
                        if text and len(text) > 200:
                            logger.debug("Quote web fallback found opinion via: %s", url)
                            return text
            except Exception as exc:
                logger.debug("Brave quote search failed for query %r: %s", query, exc)

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
