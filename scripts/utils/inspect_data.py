"""
检查: 简历数据结构 + chunk内容质量
"""
from pymongo import MongoClient

client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]

# Check resume structure
resumes = list(db.resumes.find({}).limit(3))
for r in resumes:
    print(f"Resume: {r.get('name', '?')} | keys: {list(r.keys())}")
    print(f"  source: {r.get('source_file', '?')}")
    print(f"  skills: {r.get('skills', [])[:5]}")
    print(f"  experience_years: {r.get('experience_years', '?')}")
    print(f"  education: {r.get('education', '?')}")
    print(f"  current_company: {r.get('current_company', '?')}")
    print()

# Check chunks
chunks = list(db.chunks.find({}).limit(5))
print(f"\nTotal chunks in MongoDB: {db.chunks.count_documents({})}")
for c in chunks:
    print(f"Chunk: resume_id={str(c.get('resume_id','?'))[:15]} | text_len={len(c.get('text',''))} | preview: {c.get('text','')[:100]}")
