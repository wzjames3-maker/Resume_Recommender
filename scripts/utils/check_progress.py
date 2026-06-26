from pymongo import MongoClient
client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]

# Count resumes with actual skills (processed)
with_skills = db.resumes.count_documents({"skill_list": {"$exists": True, "$ne": []}})
no_skills = db.resumes.count_documents({"skill_list": {"$size": 0}})
total = db.resumes.count_documents({})
print(f"Total: {total}")
print(f"With skills: {with_skills}")
print(f"No skills: {no_skills}")

# How many need reprocessing
need_reprocess = list(db.resumes.find({"skill_list": {"$size": 0}}, {"personal_info.full_name": 1}))
print(f"\nNeed reprocessing ({len(need_reprocess)}):")
for r in need_reprocess[:10]:
    print(f"  {r.get('personal_info', {}).get('full_name', '?')}")
