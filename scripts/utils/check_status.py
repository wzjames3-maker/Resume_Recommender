import os
from pymongo import MongoClient

mongo_uri = os.environ.get("MONGO_URI", "")
print(f"MONGO_URI env: {mongo_uri}")

for host in ["mongodb", "mongo", "localhost", "172.18.0.5"]:
    uri = f"mongodb://admin:password@{host}:27017/resume_rag?authSource=admin"
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        db = client["resume_rag"]
        count = db.resumes.count_documents({})
        print(f"SUCCESS via {host}: {count} resumes")
        break
    except Exception as e:
        print(f"FAIL via {host}: {str(e)[:80]}")
