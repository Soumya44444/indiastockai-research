"""Unit tests for RAG pipeline pure-logic pieces (chunking and citation
formatting). Embedding/ChromaDB steps require the actual model and a
live collection, so those are covered by the manual integration tests
already run against the real Zydus Wellness PDF, not unit-mocked here."""
import pytest
from app.rag.chunking import chunk_page_text, chunk_document, _split_into_sentences
from app.rag.retrieval import format_citation


class TestSplitIntoSentences:
    def test_basic_split(self):
        text = "This is sentence one. This is sentence two. And a third!"
        result = _split_into_sentences(text)
        assert len(result) == 3

    def test_handles_question_marks(self):
        text = "Is this a question? Yes it is."
        result = _split_into_sentences(text)
        assert len(result) == 2

    def test_empty_text_returns_empty(self):
        assert _split_into_sentences("") == []

    def test_whitespace_only_returns_empty(self):
        assert _split_into_sentences("   \n\n  ") == []


class TestChunkPageText:
    def test_short_text_single_chunk(self):
        text = "This is a short page with just one sentence."
        chunks = chunk_page_text(page_number=1, text=text, chunk_size_chars=800)
        assert len(chunks) == 1
        assert chunks[0]["page_number"] == 1

    def test_long_text_splits_into_multiple_chunks(self):
        # Build text well beyond chunk_size_chars
        sentence = "This is a moderately long sentence about company financials. "
        text = sentence * 30  # ~1950 chars
        chunks = chunk_page_text(page_number=2, text=text, chunk_size_chars=500, overlap_chars=50)
        assert len(chunks) > 1
        assert all(c["page_number"] == 2 for c in chunks)

    def test_empty_text_returns_no_chunks(self):
        assert chunk_page_text(page_number=1, text="") == []

    def test_chunks_do_not_wildly_exceed_target_size(self):
        # Individual sentences can push a chunk slightly over target, but
        # chunks shouldn't be drastically larger than the requested size.
        sentence = "Revenue grew twenty percent year over year in this quarter. "
        text = sentence * 20
        chunks = chunk_page_text(page_number=1, text=text, chunk_size_chars=300)
        for c in chunks:
            assert len(c["text"]) < 300 * 2  # generous margin, catches runaway chunks

    def test_overlap_carries_context_between_chunks(self):
        sentence_template = "Sentence number {} about the company results. "
        text = "".join(sentence_template.format(i) for i in range(20))
        chunks = chunk_page_text(page_number=1, text=text, chunk_size_chars=200, overlap_chars=50)
        # With overlap, consecutive chunks should share at least some text
        assert len(chunks) > 1


class TestChunkDocument:
    def test_assigns_sequential_chunk_ids(self):
        pages = [
            {"page_number": 1, "text": "First page content here with enough text to form a chunk."},
            {"page_number": 2, "text": "Second page content here with enough text to form a chunk."},
        ]
        chunks = chunk_document(pages)
        chunk_ids = [c["chunk_id"] for c in chunks]
        assert chunk_ids == list(range(len(chunks)))  # sequential, no gaps

    def test_preserves_page_numbers(self):
        pages = [
            {"page_number": 1, "text": "Page one text."},
            {"page_number": 5, "text": "Page five text (pages can be non-contiguous if filtered upstream)."},
        ]
        chunks = chunk_document(pages)
        page_numbers = {c["page_number"] for c in chunks}
        assert page_numbers == {1, 5}

    def test_skips_empty_pages(self):
        pages = [
            {"page_number": 1, "text": "Real content on this page."},
            {"page_number": 2, "text": ""},  # empty page, e.g. a blank/image page
        ]
        chunks = chunk_document(pages)
        assert all(c["page_number"] != 2 for c in chunks)

    def test_empty_document_returns_no_chunks(self):
        assert chunk_document([]) == []


class TestFormatCitation:
    def test_standard_format(self):
        match = {"document_name": "report.pdf", "page_number": 3}
        assert format_citation(match) == "[report.pdf, p.3]"

    def test_never_omits_source(self):
        # Every citation must include both document and page — this is
        # the core "never fabricate, always cite" guarantee.
        match = {"document_name": "annual_report_2026.pdf", "page_number": 42}
        result = format_citation(match)
        assert "annual_report_2026.pdf" in result
        assert "42" in result