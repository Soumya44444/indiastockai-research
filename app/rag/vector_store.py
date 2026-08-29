"""
Embedding + vector store (project spec Section 18: Extract -> Chunk ->
Embed -> Vector DB -> Retrieve -> LLM -> Answer with citations).

Zero-cost stack: sentence-transformers (local, free, no API key) for
embeddings + ChromaDB (local, persistent, free) for the vector store.
No paid embedding API is used, per the project's strict zero-cost rule.
"""
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer

# Persistent on-disk ChromaDB store — survives across script runs.
CHROMA_DB_PATH = "db/chroma"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # small, fast, free, good general-purpose model

_model = None  # lazy-loaded singleton, avoids reloading the model on every call
_client = None


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model '{EMBEDDING_MODEL_NAME}' (first run downloads it, ~90MB)...")
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def get_chroma_client():
    global _client
    if _client is None:
        Path(CHROMA_DB_PATH).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _client


def get_or_create_collection(collection_name: str = "equity_research_documents"):
    client = get_chroma_client()
    return client.get_or_create_collection(name=collection_name)


def embed_and_store_chunks(chunks: list[dict], document_name: str, ticker: str | None = None,
                            collection_name: str = "equity_research_documents") -> dict:
    """
    Embeds a list of chunks (from chunking.chunk_document) and stores them
    in ChromaDB with metadata (document name, page number, ticker if known)
    so retrieval results can always be traced back to their source —
    required for the "answer with citations, never fabricate" principle.
    """
    if not chunks:
        return {"available": False, "reason": "No chunks provided."}

    model = get_embedding_model()
    collection = get_or_create_collection(collection_name)

    texts = [c["text"] for c in chunks]
    ids = [f"{document_name}::chunk_{c['chunk_id']}" for c in chunks]
    metadatas = [
        {
            "document_name": document_name,
            "page_number": c["page_number"],
            "chunk_id": c["chunk_id"],
            "ticker": ticker or "unknown",
        }
        for c in chunks
    ]

    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    # Upsert: safe to re-run on the same document without duplicating entries.
    collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    return {
        "available": True,
        "document_name": document_name,
        "chunks_stored": len(chunks),
        "collection_name": collection_name,
    }


if __name__ == "__main__":
    import sys
    from app.rag.document_ingestion import extract_text_from_pdf
    from app.rag.chunking import chunk_document

    if len(sys.argv) < 2:
        print("Usage: python -m app.rag.vector_store <path-to-pdf>")
    else:
        pdf_path = sys.argv[1]
        doc = extract_text_from_pdf(pdf_path)

        if not doc["available"]:
            print(f"NOT AVAILABLE: {doc['reason']}")
        else:
            chunks = chunk_document(doc["pages"])
            print(f"Extracted {doc['page_count']} pages, chunked into {len(chunks)} chunks")

            result = embed_and_store_chunks(chunks, document_name=doc["file_name"], ticker="ZYDUSWELL.NS")

            if result["available"]:
                print(f"\nStored {result['chunks_stored']} chunks in ChromaDB "
                      f"collection '{result['collection_name']}'")

                # Quick sanity check: confirm the collection actually has data
                collection = get_or_create_collection()
                print(f"Collection now contains {collection.count()} total chunks")
            else:
                print(f"NOT AVAILABLE: {result['reason']}")