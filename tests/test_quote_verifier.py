"""Tests for the quote verification module."""

import unittest
from unittest.mock import MagicMock, patch

from legal_citation_checker.quote_verifier import (
    QuoteVerifier,
    QuoteVerificationResult,
    _fuzzy_quote_match,
    _normalize_for_comparison,
    _HTMLTextExtractor,
    extract_opinion_id,
    extract_cluster_id,
)


class TestNormalization(unittest.TestCase):
    """Test text normalization for comparison."""

    def test_smart_quotes(self):
        result = _normalize_for_comparison("\u201cHello\u201d")
        self.assertEqual(result, '"Hello"')

    def test_em_dash(self):
        result = _normalize_for_comparison("word\u2014word")
        self.assertEqual(result, "word--word")

    def test_whitespace_collapse(self):
        result = _normalize_for_comparison("  hello   world  ")
        self.assertEqual(result, "hello world")


class TestFuzzyQuoteMatch(unittest.TestCase):
    """Test fuzzy quote matching logic."""

    def test_exact_match(self):
        matched, similarity, _ = _fuzzy_quote_match(
            "the right of the people",
            "We hold that the right of the people to keep and bear arms is fundamental.",
        )
        self.assertTrue(matched)
        self.assertEqual(similarity, 1.0)

    def test_near_match(self):
        # Slight difference (typo or OCR artifact) — use longer haystack
        matched, similarity, _ = _fuzzy_quote_match(
            "the right of the people to keep and bear arms",
            "In this landmark case, we hold that the right of the people to keep "
            "and bear anns is a fundamental individual right deeply rooted in the "
            "Nation's history and tradition. This right applies to all citizens.",
            threshold=0.80,
        )
        self.assertTrue(matched)
        self.assertGreater(similarity, 0.80)

    def test_no_match(self):
        matched, similarity, _ = _fuzzy_quote_match(
            "completely different text about contracts and obligations",
            "We hold that the right of the people to keep and bear arms is fundamental.",
        )
        self.assertFalse(matched)
        self.assertLess(similarity, 0.5)

    def test_empty_needle(self):
        matched, similarity, _ = _fuzzy_quote_match("", "some text")
        self.assertFalse(matched)

    def test_empty_haystack(self):
        matched, similarity, _ = _fuzzy_quote_match("some text", "")
        self.assertFalse(matched)

    def test_smart_quote_normalization(self):
        matched, similarity, _ = _fuzzy_quote_match(
            "\u201cequal protection\u201d",
            'The "equal protection" clause guarantees...',
        )
        self.assertTrue(matched)


class TestHTMLExtractor(unittest.TestCase):
    """Test HTML to text extraction."""

    def test_simple_html(self):
        extractor = _HTMLTextExtractor()
        extractor.feed("<p>Hello <strong>world</strong></p>")
        self.assertIn("Hello", extractor.get_text())
        self.assertIn("world", extractor.get_text())

    def test_script_stripped(self):
        extractor = _HTMLTextExtractor()
        extractor.feed("<p>Hello</p><script>alert('x')</script><p>World</p>")
        text = extractor.get_text()
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("alert", text)

    def test_paragraph_newlines(self):
        extractor = _HTMLTextExtractor()
        extractor.feed("<p>Line one</p><p>Line two</p>")
        text = extractor.get_text()
        self.assertIn("Line one", text)
        self.assertIn("Line two", text)


class TestExtractOpinionId(unittest.TestCase):
    """Test opinion ID extraction from URLs."""

    def test_standard_url(self):
        url = "https://www.courtlistener.com/opinion/108713/brown-v-board-of-education/"
        self.assertEqual(extract_opinion_id(url), "108713")

    def test_api_url(self):
        url = "https://www.courtlistener.com/api/rest/v4/opinions/108713/"
        self.assertEqual(extract_opinion_id(url), "108713")

    def test_no_opinion_id(self):
        url = "https://www.courtlistener.com/docket/12345/"
        self.assertIsNone(extract_opinion_id(url))

    def test_empty_url(self):
        self.assertIsNone(extract_opinion_id(""))
        self.assertIsNone(extract_opinion_id(None))


class TestExtractClusterId(unittest.TestCase):
    """Test cluster ID extraction from URLs."""

    def test_cluster_url(self):
        url = "https://www.courtlistener.com/clusters/12345/"
        self.assertEqual(extract_cluster_id(url), "12345")

    def test_no_cluster(self):
        url = "https://www.courtlistener.com/opinion/108713/"
        self.assertIsNone(extract_cluster_id(url))


class TestQuoteVerifier(unittest.TestCase):
    """Test the QuoteVerifier class."""

    def test_short_quote_skipped(self):
        """Quotes under 10 chars should be skipped."""
        qv = QuoteVerifier(session=None)
        result = qv.verify_quote("short", source_url="http://example.com/opinion/1/")
        self.assertEqual(result.status, "skipped")

    def test_no_source_url(self):
        """Missing source URL should return no_source."""
        qv = QuoteVerifier(session=None)
        result = qv.verify_quote(
            "a sufficiently long quote for testing",
            source_url=None,
        )
        self.assertEqual(result.status, "no_source")

    def test_no_session(self):
        """No HTTP session should return text_unavailable."""
        qv = QuoteVerifier(session=None)
        result = qv.verify_quote(
            "a sufficiently long quote for testing",
            source_url="https://www.courtlistener.com/opinion/108713/case/",
        )
        self.assertEqual(result.status, "text_unavailable")

    def test_verified_quote_with_mock(self):
        """Mock opinion text and verify a matching quote."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "plain_text": (
                "SUPREME COURT OF THE UNITED STATES\n\n"
                "We hold that the right of the people to keep and bear arms "
                "is a fundamental individual right. This right is deeply rooted "
                "in our Nation's history and tradition."
            ),
        }
        mock_session.get.return_value = mock_response

        qv = QuoteVerifier(session=mock_session, api_token="test-token")
        result = qv.verify_quote(
            quote_text="the right of the people to keep and bear arms",
            source_url="https://www.courtlistener.com/opinion/108713/dc-v-heller/",
        )
        self.assertEqual(result.status, "verified")
        self.assertGreaterEqual(result.confidence, 80)
        self.assertIsNotNone(result.similarity)
        self.assertGreaterEqual(result.similarity, 0.8)

    def test_fabricated_quote_with_mock(self):
        """Mock opinion text and verify a non-matching quote is flagged."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "plain_text": (
                "SUPREME COURT OF THE UNITED STATES\n\n"
                "This case concerns the interpretation of the Commerce Clause "
                "and its application to interstate trade regulations. "
                "The court finds that Congress has the power to regulate "
                "channels and instrumentalities of interstate commerce."
            ),
        }
        mock_session.get.return_value = mock_response

        qv = QuoteVerifier(session=mock_session, api_token="test-token")
        result = qv.verify_quote(
            quote_text="the right of the people to keep and bear arms is fundamental",
            source_url="https://www.courtlistener.com/opinion/108713/case/",
        )
        self.assertEqual(result.status, "not_found")
        self.assertGreaterEqual(result.confidence, 80)

    def test_html_fallback(self):
        """When API returns 403, fall back to HTML page."""
        mock_session = MagicMock()

        # First call (API) returns 403, second call (HTML) returns opinion page
        api_response = MagicMock()
        api_response.status_code = 403

        html_response = MagicMock()
        html_response.status_code = 200
        html_response.text = """
        <html><body>
        <div id="opinion-content">
        <p>We hold that separate educational facilities are inherently unequal.
        Therefore, we hold that the plaintiffs are deprived of the equal
        protection of the laws guaranteed by the Fourteenth Amendment.</p>
        </div>
        </body></html>
        """
        mock_session.get.side_effect = [api_response, html_response]

        qv = QuoteVerifier(session=mock_session, api_token="test-token")
        result = qv.verify_quote(
            quote_text="separate educational facilities are inherently unequal",
            source_url="https://www.courtlistener.com/opinion/108713/brown-v-board/",
        )
        self.assertEqual(result.status, "verified")

    def test_opinion_cache(self):
        """Second call for same opinion should use cache."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "plain_text": (
                "The court holds that due process requires notice and hearing. "
                "This fundamental principle has been recognized since the founding "
                "of our republic and remains central to our jurisprudence."
            ),
        }
        mock_session.get.return_value = mock_response

        qv = QuoteVerifier(session=mock_session, api_token="test-token")

        # First call
        qv.verify_quote(
            "due process requires notice and hearing",
            source_url="https://www.courtlistener.com/opinion/99999/test/",
        )
        # Second call - should use cache, not make another API call
        qv.verify_quote(
            "due process requires notice",
            source_url="https://www.courtlistener.com/opinion/99999/test/",
        )

        # Only one API call should have been made (cached)
        self.assertEqual(mock_session.get.call_count, 1)

    def test_result_to_dict(self):
        """QuoteVerificationResult serialization."""
        result = QuoteVerificationResult(
            status="verified",
            confidence=95,
            evidence="Quote found.",
            matched_text="the matching text",
            similarity=0.95,
        )
        d = result.to_dict()
        self.assertEqual(d["status"], "verified")
        self.assertEqual(d["confidence"], 95)
        self.assertEqual(d["similarity"], 0.95)
        self.assertIn("matched_text", d)


class TestQuoteVerifierHTMLExtraction(unittest.TestCase):
    """Test opinion text extraction from HTML pages."""

    def test_opinion_content_div(self):
        """Extract text from opinion-content div."""
        qv = QuoteVerifier(session=None)
        html = """
        <html><body>
        <nav>Navigation stuff</nav>
        <div id="opinion-content">
        <p>The court finds that the defendant's actions violated the
        plaintiff's constitutional rights under the Fourth Amendment.</p>
        </div>
        <footer>Footer stuff</footer>
        </body></html>
        """
        text = qv._extract_opinion_from_html(html)
        self.assertIsNotNone(text)
        self.assertIn("Fourth Amendment", text)
        self.assertNotIn("Navigation", text)

    def test_plaintext_pre(self):
        """Extract text from plaintext pre tag."""
        qv = QuoteVerifier(session=None)
        html = """
        <html><body>
        <pre class="plaintext">
        SUPREME COURT OF THE UNITED STATES
        The holding of the lower court is affirmed.
        Due process requires that notice be given.
        </pre>
        </body></html>
        """
        text = qv._extract_opinion_from_html(html)
        self.assertIsNotNone(text)
        self.assertIn("Due process", text)

    def test_body_fallback(self):
        """Fall back to full body text when no opinion container found."""
        qv = QuoteVerifier(session=None)
        # Long body text without recognized containers
        content = " ".join(["This is opinion text about legal matters."] * 50)
        html = f"<html><body><div>{content}</div></body></html>"
        text = qv._extract_opinion_from_html(html)
        self.assertIsNotNone(text)
        self.assertIn("legal matters", text)


if __name__ == "__main__":
    unittest.main()
