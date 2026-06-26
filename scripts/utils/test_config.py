import sys
sys.path.insert(0, ".")
from src.common.config import get_settings
s = get_settings()
print("LLM_MODEL:", s.llm.LLM_MODEL)
print("LLM_BASE_URL:", s.llm.LLM_BASE_URL)
print("LLM_API_KEY:", s.llm.LLM_API_KEY[:10])
print("EMBEDDING_MODEL:", s.embedding.EMBEDDING_MODEL)
print("EMBEDDING_BASE_URL:", s.embedding.EMBEDDING_BASE_URL)
print("RERANKER_MODEL:", s.reranker.RERANKER_MODEL)
print("OCR_MODEL:", s.ocr.OCR_MODEL)
print("MONGODB_URL:", s.mongodb.MONGODB_URL)
