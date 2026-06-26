from src.common.config import get_settings
s = get_settings()
print("MILVUS_URI:", s.milvus.MILVUS_URI)
print("MONGO_URL:", s.mongodb.url)
