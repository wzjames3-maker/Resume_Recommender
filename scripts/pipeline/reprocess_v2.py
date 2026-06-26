"""
Re-process all 111 resumes: LLM extract structured fields + re-index Milvus
FIXED: SkillEntry uses proficiency/years_of_experience, not level/years
"""
import json
import time
import traceback
from pymongo import MongoClient

client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]

from src.resume_parser.llm_extractor import get_llm_extractor
from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index
from src.resume_parser.segmenter import get_segmenter

extractor = get_llm_extractor()

resumes = list(db.resumes.find({}))
print(f"Total resumes to re-process: {len(resumes)}")

print("=" * 60)
print("PHASE 1: Re-extract structured fields via LLM")
print("=" * 60)

updated = 0
failed = 0
start_all = time.time()

for i, doc in enumerate(resumes):
    rid = str(doc["_id"])
    raw = doc.get("raw_text", "")
    if not raw:
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
        skills_count = len(structured.skill_list)
        if (i + 1) % 5 == 0:
            elapsed = time.time() - start_all
            rate = (i + 1) / elapsed
            eta = (len(resumes) - i - 1) / rate
            print(f"  [{i+1}/{len(resumes)}] {name} | skills={skills_count} | updated={updated} failed={failed} | {rate:.1f}/s ETA:{eta:.0f}s")
    except Exception as e:
        failed += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}] ERR: {str(e)[:80]}")

elapsed = time.time() - start_all
print(f"\nPhase 1 done: updated={updated} failed={failed} time={elapsed:.0f}s")

# Step 2: Delete old Milvus chunks and re-index
print("\n" + "=" * 60)
print("PHASE 2: Re-index Milvus vectors")
print("=" * 60)

from pymilvus import connections, Collection, utility
from src.common.config import get_settings
settings = get_settings()

try:
    connections.disconnect("default")
except:
    pass
connections.connect(alias="default", uri=settings.milvus.MILVUS_URI)

COLLECTION_NAME = "resume_chunks"
if utility.has_collection(COLLECTION_NAME):
    col = Collection(COLLECTION_NAME)
    col.drop()
    print(f"Dropped old collection: {COLLECTION_NAME}")

# Re-init
from src.vector_index.index import MilvusVectorIndex
idx2 = MilvusVectorIndex()
gen = get_embedding_generator()
seg = get_segmenter()

resumes = list(db.resumes.find({}))
indexed = 0
total_chunks = 0

for i, doc in enumerate(resumes):
    rid = str(doc["_id"])
    raw = doc.get("raw_text", "")
    pi = doc.get("personal_info", {})
    name = pi.get("full_name", "?") if isinstance(pi, dict) else "?"
    
    if not raw:
        continue
    
    try:
        result = seg.segment(raw)
        count = 0
        for si, s in enumerate(result.segments):
            text = s.content
            chunks_list = []
            if len(text) > 500:
                lines = text.split("\n")
                buf = ""
                for ln in lines:
                    if len(buf) + len(ln) > 300 and buf:
                        chunks_list.append(buf.strip())
                        buf = ln
                    else:
                        buf += "\n" + ln if buf else ln
                if buf.strip():
                    chunks_list.append(buf.strip())
            else:
                chunks_list = [text]
            
            for j, ct in enumerate(chunks_list):
                if not ct.strip():
                    continue
                emb = gen.generate(ct)
                data = [{
                    "chunk_id": rid + "_s" + str(si) + "_c" + str(j),
                    "resume_id": rid,
                    "chunk_level": "small",
                    "parent_chunk_id": rid + "_s" + str(si),
                    "section_type": s.segment_type.value,
                    "dense_vector": emb.dense,
                    "sparse_vector": emb.sparse,
                    "content": ct[:2000],
                    "metadata": {"name": name},
                }]
                idx2.insert_chunks(data)
                count += 1
        
        indexed += 1
        total_chunks += count
    except Exception as e:
        print(f"  [IDX ERR] {name}: {str(e)[:80]}")
    
    if (i + 1) % 10 == 0:
        print(f"  Index: {i+1}/{len(resumes)} | indexed={indexed} chunks={total_chunks}")

# Reload
try:
    col = Collection(COLLECTION_NAME)
    col.release()
    col.load()
    time.sleep(2)
    entities = col.num_entities
    print(f"\nMilvus: {entities} entities")
except Exception as e:
    print(f"Reload: {e}")
    entities = total_chunks

total_elapsed = time.time() - start_all
print(f"\n{'='*60}")
print(f"COMPLETE: MongoDB={updated} updated, Milvus={indexed} resumes / {total_chunks} chunks / {entities} entities")
print(f"Total time: {total_elapsed:.0f}s")
