"""Tests for the proposition-level quote-citation binding engine."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from legal_citation_checker.proposition_binder import (
    PropositionBinder,
    segment_sentences,
    extract_quotes,
)


class TestSentenceSegmentation:
    def test_simple_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        sents = segment_sentences(text)
        assert len(sents) == 3
        assert sents[0].text == "First sentence."
        assert sents[1].text == "Second sentence."

    def test_legal_abbreviations_not_split(self):
        text = "See Smith v. Jones, 347 U.S. 483 (1954). The court held otherwise."
        sents = segment_sentences(text)
        # "U.S." should NOT split the sentence
        assert len(sents) == 2
        assert "347 U.S. 483" in sents[0].text

    def test_mr_mrs_not_split(self):
        text = "Mr. Smith testified. Mrs. Jones disagreed."
        sents = segment_sentences(text)
        assert len(sents) == 2

    def test_citation_abbreviations(self):
        text = "The court in Dep. of Smith found liability. The result was clear."
        sents = segment_sentences(text)
        assert len(sents) == 2


class TestQuoteExtraction:
    def test_double_quotes(self):
        text = 'The court said "this is important evidence" in its ruling.'
        quotes = extract_quotes(text)
        assert len(quotes) == 1
        assert quotes[0].text == "this is important evidence"

    def test_smart_quotes(self):
        text = 'The witness stated \u201cI never saw the document\u201d under oath.'
        quotes = extract_quotes(text)
        assert len(quotes) == 1
        assert quotes[0].text == "I never saw the document"

    def test_short_quotes_filtered(self):
        text = 'He said "yes" and she said "absolutely not under any circumstances".'
        quotes = extract_quotes(text)
        # "yes" is too short (< 10 chars), should be filtered
        assert len(quotes) == 1
        assert "absolutely" in quotes[0].text

    def test_multiple_quotes(self):
        text = (
            'First quote: "the evidence clearly shows liability" and '
            'second quote: "damages exceed ten million dollars" in the record.'
        )
        quotes = extract_quotes(text)
        assert len(quotes) == 2


class TestPropositionBinder:
    def test_tier2_same_sentence_binding(self):
        """Quote and citation in same sentence → high confidence."""
        # Citation within the same sentence as the quote
        text = (
            'The CTO admitted "we migrated without permission" Smith Dep. 42:20. '
            'The next witness corroborated this.'
        )
        binder = PropositionBinder(text)
        cite_start = text.index("Smith Dep. 42:20")
        cite_end = cite_start + len("Smith Dep. 42:20")
        binder.register_citation(cite_start, cite_end, "Smith Dep. 42:20")

        result = binder.get_quote_for_citation(cite_start, cite_end)
        assert result is not None
        quote_text, confidence = result
        assert "migrated without permission" in quote_text
        assert confidence >= 0.85

    def test_tier3_adjacent_sentence_binding(self):
        """Quote in one sentence, citation in next → tier 3 confidence."""
        text = (
            'The CTO admitted "we migrated without permission" in his testimony. '
            'Smith Dep. 42:20. The next witness corroborated this.'
        )
        binder = PropositionBinder(text)
        cite_start = text.index("Smith Dep. 42:20")
        cite_end = cite_start + len("Smith Dep. 42:20")
        binder.register_citation(cite_start, cite_end, "Smith Dep. 42:20")

        result = binder.get_quote_for_citation(cite_start, cite_end)
        assert result is not None
        quote_text, confidence = result
        assert "migrated without permission" in quote_text
        assert confidence >= 0.70  # tier 3: paragraph-level binding

    def test_tier3_quote_precedes_citation(self):
        """Quote before citation in same paragraph → medium confidence."""
        text = (
            '"The outages caused significant harm to our business." '
            "Plaintiff's CFO further explained the financial impact. "
            "Johnson Decl. ¶ 4."
        )
        binder = PropositionBinder(text)
        cite_start = text.index("Johnson Decl.")
        cite_end = cite_start + len("Johnson Decl. ¶ 4")
        binder.register_citation(cite_start, cite_end, "Johnson Decl. ¶ 4")

        result = binder.get_quote_for_citation(cite_start, cite_end)
        assert result is not None
        quote_text, confidence = result
        assert "outages caused significant harm" in quote_text
        assert confidence >= 0.70

    def test_no_binding_when_no_quote(self):
        """Citation with no nearby quote → no binding."""
        text = "The complaint was filed on January 15. Compl. ¶ 1. The case proceeded."
        binder = PropositionBinder(text)
        cite_start = text.index("Compl. ¶ 1")
        cite_end = cite_start + len("Compl. ¶ 1")
        binder.register_citation(cite_start, cite_end, "Compl. ¶ 1")

        result = binder.get_quote_for_citation(cite_start, cite_end)
        assert result is None

    def test_quote_binds_to_correct_citation_same_sentence(self):
        """When two citations in a paragraph, quote binds to nearest forward."""
        # Quote and Ex. A in same sentence (no period between them)
        text = (
            'The contract stated "99.99% uptime guaranteed" as a material term, '
            "see Ex. A at 3, and Defendant breached this guarantee repeatedly, "
            "Compl. ¶ 14."
        )
        binder = PropositionBinder(text)

        ex_start = text.index("Ex. A at 3")
        ex_end = ex_start + len("Ex. A at 3")
        binder.register_citation(ex_start, ex_end, "Ex. A at 3")

        compl_start = text.index("Compl. ¶ 14")
        compl_end = compl_start + len("Compl. ¶ 14")
        binder.register_citation(compl_start, compl_end, "Compl. ¶ 14")

        # Quote should bind to Ex. A (nearest forward cite)
        ex_result = binder.get_quote_for_citation(ex_start, ex_end)
        assert ex_result is not None
        assert "99.99% uptime" in ex_result[0]

    def test_quote_binds_to_nearest_forward_citation(self):
        """Quote precedes two citations — binds with reduced confidence."""
        text = (
            '"The outages lasted 340 hours." Smith Dep. 45:4. '
            "Johnson Decl. ¶ 8."
        )
        # Use lower threshold since multiple competing cites reduce confidence
        binder = PropositionBinder(text, binding_threshold=0.50)

        smith_start = text.index("Smith Dep. 45:4")
        smith_end = smith_start + len("Smith Dep. 45:4")
        binder.register_citation(smith_start, smith_end, "Smith Dep. 45:4")

        johnson_start = text.index("Johnson Decl. ¶ 8")
        johnson_end = johnson_start + len("Johnson Decl. ¶ 8")
        binder.register_citation(johnson_start, johnson_end, "Johnson Decl. ¶ 8")

        # Quote binds to Smith (nearest forward cite) but at reduced confidence
        smith_result = binder.get_quote_for_citation(smith_start, smith_end)
        assert smith_result is not None
        assert "340 hours" in smith_result[0]
        # Confidence is reduced because multiple forward cites compete
        assert smith_result[1] >= 0.50
        assert smith_result[1] < 0.75  # not high confidence with ambiguity

    def test_unambiguous_single_forward_cite(self):
        """Quote with only one forward cite → higher confidence."""
        text = (
            '"The outages lasted 340 hours." Smith Dep. 45:4.'
        )
        binder = PropositionBinder(text)

        smith_start = text.index("Smith Dep. 45:4")
        smith_end = smith_start + len("Smith Dep. 45:4")
        binder.register_citation(smith_start, smith_end, "Smith Dep. 45:4")

        smith_result = binder.get_quote_for_citation(smith_start, smith_end)
        assert smith_result is not None
        assert "340 hours" in smith_result[0]
        assert smith_result[1] >= 0.70  # unambiguous → above threshold

    def test_floating_quotes_detected(self):
        """Quotes with no citation in their paragraph should float."""
        text = (
            '"This is an important statement about the case." '
            "The parties dispute the facts.\n\n"
            "A separate paragraph with no quotes. Compl. ¶ 1."
        )
        binder = PropositionBinder(text)
        cite_start = text.index("Compl. ¶ 1")
        cite_end = cite_start + len("Compl. ¶ 1")
        binder.register_citation(cite_start, cite_end, "Compl. ¶ 1")

        floating = binder.floating_quotes()
        assert len(floating) >= 1
        assert any("important statement" in q.text for q in floating)

    def test_binding_summary(self):
        """Binding summary provides correct counts."""
        text = (
            'He said "the migration caused the outages" under oath. Smith Dep. 42:20.\n\n'
            '"Unsupported claim without any citation nearby." The facts are disputed.'
        )
        binder = PropositionBinder(text)
        cite_start = text.index("Smith Dep. 42:20")
        cite_end = cite_start + len("Smith Dep. 42:20")
        binder.register_citation(cite_start, cite_end, "Smith Dep. 42:20")

        summary = binder.binding_summary()
        assert summary["total_quotes"] == 2
        assert summary["total_citations"] == 1
        assert summary["bound_above_threshold"] >= 1
        assert summary["floating_quotes"] >= 1


class TestEdgeCases:
    def test_empty_text(self):
        binder = PropositionBinder("")
        assert binder.bind() == []
        assert binder.floating_quotes() == []

    def test_no_citations_registered(self):
        text = '"A quote" with no citations anywhere.'
        binder = PropositionBinder(text)
        floating = binder.floating_quotes()
        # Short quote filtered out, so no floating quotes
        assert len(floating) == 0

    def test_no_quotes_in_text(self):
        text = "No quotes at all. Compl. ¶ 1."
        binder = PropositionBinder(text)
        cite_start = text.index("Compl. ¶ 1")
        binder.register_citation(cite_start, cite_start + 10, "Compl. ¶ 1")
        assert binder.get_quote_for_citation(cite_start, cite_start + 10) is None
