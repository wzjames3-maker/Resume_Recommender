"""
检查简历详细结构
"""
import json
from pymongo import MongoClient

client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]

# Full structure of first resume
r = db.resumes.find_one({})
print("First resume full structure:")
# Remove raw_text for readability
r_copy = {k: v for k, v in r.items() if k != 'raw_text'}
print(json.dumps(r_copy, ensure_ascii=False, indent=2, default=str))

print(f"\npersonal_info: {json.dumps(r.get('personal_info', {}), ensure_ascii=False, indent=2)}")
print(f"\nskill_list: {r.get('skill_list', [])[:5]}")
print(f"\neducation_list: {json.dumps(r.get('education_list', [])[:1], ensure_ascii=False, indent=2)}")
print(f"\nexperience_list: {json.dumps(r.get('experience_list', [])[:1], ensure_ascii=False, indent=2)}")

# Count by source_type
pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
for item in db.resumes.aggregate(pipeline):
    print(f"Status: {item['_id']} -> {item['count']}")
