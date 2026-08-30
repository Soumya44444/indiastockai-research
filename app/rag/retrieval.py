"""
Retrieval with citations (project spec Section 18: Retrieve -> LLM ->
Answer with citations). This module handles retrieval only — embedding
a query, searching ChromaDB, and returning ranked chunks with full
citation metadata. The LLM answer-generation step is Phase 9 (chatbot);
this module's job is to guarantee that whatever the LLM eventually says
can be traced back to an exact document + page.
"""
from app.rag.vector_store import get_embedding_model, get_or_create_collection


def search_documents(query: str, top_k: int = 5, ticker: str | None = None,
                      collection_name: str = "equity_research_documents") -> dict:
    """
    Embeds a natural-language query and retrieves the top_k most relevant
    chunks from ChromaDB, each with full citation metadata (document name,
    page number). Optionally filters to a specific ticker's documents only.

    Returns explicit "no results" rather than fabricating an answer when
    the collection is empty or nothing relevant is found.
    """
    collection = get_or_create_collection(collection_name)

    if collection.count() == 0:
        return {"available": False, "reason": "No documents have been ingested into this collection yet."}

    model = get_embedding_model()
    query_embedding = model.encode([query]).tolist()

    where_filter = {"ticker": ticker} if ticker else None

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
        where=where_filter,
    )

    if not results["ids"] or not results["ids"][0]:
        return {"available": False, "reason": "No matching results found for this query."}

    matches = []
    for i in range(len(results["ids"][0])):
        metadata = results["metadatas"][0][i]
        # ChromaDB returns distance (lower = more similar); convert to a
        # more intuitive 0-1 relevance score for display.
        distance = results["distances"][0][i]
        relevance_score = max(0.0, 1 - distance)

        matches.append({
            "text": results["documents"][0][i],
            "document_name": metadata["document_name"],
            "page_number": metadata["page_number"],
            "ticker": metadata.get("ticker"),
            "relevance_score": relevance_score,
        })

    return {
        "available": True,
        "query": query,
        "match_count": len(matches),
        "matches": matches,
    }


def format_citation(match: dict) -> str:
    """Standard citation format used throughout the app — never omit the source."""
    return f"[{match['document_name']}, p.{match['page_number']}]"


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the price target and rating for Zydus Wellness?"

    print(f"Query: {query}\n")
    result = search_documents(query, top_k=3)

    if not result["available"]:
        print(f"NOT AVAILABLE: {result['reason']}")
    else:
        print(f"Found {result['match_count']} relevant chunks:\n")
        for i, m in enumerate(result["matches"], 1):
            print(f"{i}. {format_citation(m)} (relevance: {m['relevance_score']:.2f})")
            print(f"   {m['text'][:300]}")
            print()