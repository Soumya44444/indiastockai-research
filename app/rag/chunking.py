"""
Chunking (project spec Section 18: RAG pipeline Extract -> Chunk -> Embed
-> Vector DB -> Retrieve -> LLM -> Answer with citations).

Splits page-level extracted text into overlapping chunks suitable for
embedding, while preserving page-number metadata — essential for the
"answer with citations" requirement (never fabricate document content;
always trace an answer back to its source page).
"""
import re


def _split_into_sentences(text: str) -> list[str]:
    """Simple sentence splitter — good enough for financial report prose
    (no need for a heavy NLP dependency for this)."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def chunk_page_text(page_number: int, text: str, chunk_size_chars: int = 800,
                     overlap_chars: int = 150) -> list[dict]:
    """
    Chunks a single page's text into overlapping segments, breaking on
    sentence boundaries where possible (avoids cutting mid-sentence,
    which would hurt embedding quality and citation readability).
    """
    if not text.strip():
        return []

    sentences = _split_into_sentences(text)
    if not sentences:
        return []

    chunks = []
    current_chunk_sentences = []
    current_length = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        if current_length + sentence_len > chunk_size_chars and current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            chunks.append({"page_number": page_number, "text": chunk_text})

            # Build overlap: keep trailing sentences whose combined length
            # is roughly overlap_chars, so context carries into the next chunk.
            overlap_sentences = []
            overlap_len = 0
            for s in reversed(current_chunk_sentences):
                if overlap_len >= overlap_chars:
                    break
                overlap_sentences.insert(0, s)
                overlap_len += len(s)

            current_chunk_sentences = overlap_sentences
            current_length = overlap_len

        current_chunk_sentences.append(sentence)
        current_length += sentence_len

    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        chunks.append({"page_number": page_number, "text": chunk_text})

    return chunks


def chunk_document(pages: list[dict], chunk_size_chars: int = 800,
                    overlap_chars: int = 150) -> list[dict]:
    """
    Chunks an entire document (list of {page_number, text} dicts, as
    returned by document_ingestion.extract_text_from_pdf). Each output
    chunk carries a chunk_id (sequential) and its source page_number,
    so retrieval results can always be cited back to a specific page.
    """
    all_chunks = []
    chunk_id = 0

    for page in pages:
        page_chunks = chunk_page_text(page["page_number"], page["text"],
                                       chunk_size_chars, overlap_chars)
        for c in page_chunks:
            all_chunks.append({
                "chunk_id": chunk_id,
                "page_number": c["page_number"],
                "text": c["text"],
                "char_count": len(c["text"]),
            })
            chunk_id += 1

    return all_chunks


if __name__ == "__main__":
    import sys
    from app.rag.document_ingestion import extract_text_from_pdf

    if len(sys.argv) < 2:
        print("Usage: python -m app.rag.chunking <path-to-pdf>")
    else:
        doc = extract_text_from_pdf(sys.argv[1])
        if not doc["available"]:
            print(f"NOT AVAILABLE: {doc['reason']}")
        else:
            chunks = chunk_document(doc["pages"])
            print(f"Document: {doc['file_name']} ({doc['page_count']} pages, {doc['total_characters']} chars)")
            print(f"Chunked into {len(chunks)} chunks\n")

            for c in chunks[:3]:
                print(f"[Chunk {c['chunk_id']}, Page {c['page_number']}, {c['char_count']} chars]")
                print(f"  {c['text'][:200]}...")
                print()

            avg_size = sum(c["char_count"] for c in chunks) / len(chunks)
            print(f"Average chunk size: {avg_size:.0f} chars")