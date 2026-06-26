"""
Phase 2: Rebuild Milvus vector index from scratch
"""
import os
os.environ["LLM_API_KEY"] = "sk-VUB68i3rx1MJDKTesI9mQezOP4aPmPv3"

import time
from pymongo import MongoClient

client = MongoClient("mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
db = client["resume_rag"]
resumes = list(db.resumes.find({}))
print(f"Total resumes to index: {len(resumes)}")

from src.vector_index.index import get_vector_index
from src.vector_index.embedding_generator import get_embedding_generator
from src.resume_parser.segmenter import get_segmenter

idx = get_vector_index()

# Recreate collection
print("Creating collection and indexes...")
idx.create_collection()
idx.create_indexes()
print("Collection created successfully")

gen = get_embedding_generator()
seg = get_segmenter()

indexed = 0
failed = 0
total_chunks = 0
start = time.time()

for i, doc in enumerate(resumes):
    rid = str(doc["_id"])
    raw = doc.get("raw_text", "")
    pi = doc.get("personal_info", {})
    name = pi.get("full_name", "?") if isinstance(pi, dict) else "?"
    
    if not raw:
        failed += 1
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
                idx.insert_chunks(data)
                count += 1
        
        indexed += 1
        total_chunks += count
    except Exception as e:
        failed += 1
        print(f"  [ERR] {name}: {str(e)[:80]}")
    
    if (i + 1) % 10 == 0:
        elapsed = time.time() - start
        rate = (i + 1) / elapsed
        eta = (len(resumes) - i - 1) / rate
        print(f"  [{i+1}/{len(resumes)}] indexed={indexed} failed={failed} chunks={total_chunks} | {rate:.1f}/s ETA:{eta:.0f}s")

# Reload
print("\nReloading collection...")
try:
    from pymilvus import Collection
    col = Collection("resume_chunks")
    col.release()
    col.load()
    time.sleep(2)
    entities = col.num_entities
    print(f"Milvus: {entities} entities")
except Exception as e:
    print(f"Reload: {e}")
    entities = total_chunks

elapsed = time.time() - start
print(f"\nINDEX COMPLETE: {indexed}/{len(resumes)} resumes, {total_chunks} chunks, {entities} entities, {elapsed:.0f}s")
