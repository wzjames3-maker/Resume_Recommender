from pymongo import MongoClient
client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]
samples = list(db.resumes.find({}, {"personal_info.full_name": 1, "skill_list": 1}).limit(5))
for s in samples:
    pi = s.get("personal_info", {})
    fn = pi.get("full_name")
    sk = s.get("skill_list", [])
    print(f"name={fn} type={type(fn).__name__} skills={len(sk)}")
