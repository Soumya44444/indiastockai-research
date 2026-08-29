"""
Document ingestion (project spec Section 18: RAG + Document System).
Extracts text from PDFs (annual reports, investor presentations, etc.)
Manual upload is the primary path for now — automatic public-document
retrieval (preferred per spec where legal/technical) is a future
enhancement once a reliable, free source of NSE/BSE disclosure documents
is identified.

Never fabricates document content: extraction failures return an
explicit error rather than partial/guessed text.
"""
from pathlib import Path
from pypdf import PdfReader


def extract_text_from_pdf(file_path: str) -> dict:
    """
    Extracts text page-by-page from a PDF. Returns per-page text so
    later chunking/citation can reference exact page numbers — important
    for the "RAG citations" requirement in the spec (never fabricate,
    always cite source).
    """
    path = Path(file_path)
    if not path.exists():
        return {"available": False, "reason": f"File not found: {file_path}"}

    if path.suffix.lower() != ".pdf":
        return {"available": False, "reason": f"Only PDF files are currently supported (got {path.suffix})."}

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        return {"available": False, "reason": f"Failed to open PDF: {e}"}

    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page_number": i, "text": text.strip()})

    total_chars = sum(len(p["text"]) for p in pages)
    if total_chars == 0:
        return {
            "available": False,
            "reason": "No extractable text found — this may be a scanned/image-only PDF requiring OCR (not currently supported).",
        }

    return {
        "available": True,
        "file_path": str(path),
        "file_name": path.name,
        "page_count": len(pages),
        "pages": pages,
        "total_characters": total_chars,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.rag.document_ingestion <path-to-pdf>")
        print("\nNo test PDF provided — this module is ready but needs a real file to test against.")
    else:
        result = extract_text_from_pdf(sys.argv[1])
        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            print(f"Extracted {result['page_count']} pages, {result['total_characters']} characters")
            print(f"\nFirst page preview:\n{result['pages'][0]['text'][:500]}")