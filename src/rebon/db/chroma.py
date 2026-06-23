"""
Shared ChromaDB client and embedding function.
"""

from pathlib import Path
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

CHROMA_DIR = Path(__file__).parents[3] / "data" / "chroma"

# Requires Ollama running: ollama pull nomic-embed-text
EMBEDDING_FN = OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="nomic-embed-text",
)


def get_client() -> chromadb.PersistentClient:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))
