"""
Reprocess remaining 10 resumes with new API key
Override env var directly before importing modules
"""
import os
os.environ["LLM_API_KEY"] = "sk-VUB68i3rx1MJDKTesI9mQezOP4aPmPv3"

import time
from pymongo import MongoClient

client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]

# Find resumes without skills
need_reprocess = list(db.resumes.find({"skill_list": {"$size": 0}}))
print(f"Resumes needing reprocessing: {len(need_reprocess)}")

from src.resume_parser.llm_extractor import get_llm_extractor
extractor = get_llm_extractor()
print(f"Using model: {extractor.model}, key: {extractor.api_key[:10]}...")

updated = 0
failed = 0
start = time.time()

for i, doc in enumerate(need_reprocess):
    rid = str(doc["_id"])
    raw = doc.get("raw_text", "")
    if not raw:
        print(f"  [{i+1}] SKIP no raw_text")
        failed += 1
        continue
    
    try:
        structured = extractor.extract(raw)
        update_data = {
            "personal_info": {
                "full_name": structured.personal_info.full_name,
                "phone": structured.personal_info.phone,
                "email": structured.personal_info.email,
                "city": structured.personal_info.city,
                "birth_year": structured.personal_info.birth_year,
                "gender": structured.personal_info.gender,
                "years_of_experience": structured.personal_info.years_of_experience,
                "current_company": structured.personal_info.current_company,
                "current_title": structured.personal_info.current_title,
                "expected_city": structured.personal_info.expected_city,
                "expected_salary_range": structured.personal_info.expected_salary_range,
                "summary": structured.personal_info.summary,
            },
            "education_list": [e.model_dump() for e in structured.education_list],
            "experience_list": [e.model_dump() for e in structured.experience_list],
            "project_list": [p.model_dump() for p in structured.project_list],
            "skill_list": [{"name": s.name, "proficiency": s.proficiency, "years_of_experience": s.years_of_experience, "category": s.category} for s in structured.skill_list],
        }
        db.resumes.update_one({"_id": doc["_id"]}, {"$set": update_data})
        updated += 1
        name = structured.personal_info.full_name or "?"
        print(f"  [{i+1}/{len(need_reprocess)}] {name} skills={len(structured.skill_list)} OK")
    except Exception as e:
        failed += 1
        print(f"  [{i+1}/{len(need_reprocess)}] ERR: {str(e)[:80]}")

elapsed = time.time() - start
print(f"\nDone: updated={updated} failed={failed} time={elapsed:.0f}s")

# Verify all processed
remaining = db.resumes.count_documents({"skill_list": {"$size": 0}})
total = db.resumes.count_documents({})
print(f"Remaining unprocessed: {remaining}/{total}")
