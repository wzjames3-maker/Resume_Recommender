#!/usr/bin/env python3
"""Batch upload + index 100 generated resumes"""
import json, os, httpx, time, traceback

BASE = "http://localhost:8000"

# Login
resp = httpx.post(BASE+"/api/v1/auth/login", json={"username":"admin","password":"admin123"})
token = resp.json()["token"]
auth = {"Authorization": "Bearer " + token}

resume_dir = "generated_resumes"
files = sorted([f for f in os.listdir(resume_dir) if f.endswith(".json")])
print(f"Found {len(files)} resume files")

print("=" * 60)
print("PHASE 1: Upload resumes")
print("=" * 60)

upload_ok = 0
upload_skip = 0
upload_fail = 0
resume_ids = []

for i, fname in enumerate(files):
    fpath = os.path.join(resume_dir, fname)
    with open(fpath, "r", encoding="utf-8") as fp:
        rd = fp.read()
    
    files_data = {"file": (fname, rd, "application/json")}
    try:
        r = httpx.post(BASE+"/api/v1/resumes/upload", headers=auth, files=files_data, timeout=120)
        data = r.json()
        rid = data.get("resume_id", "")
        status = data.get("parse_status", "")
        if status == "skipped":
            upload_skip += 1
        elif r.status_code in (200, 201):
            upload_ok += 1
        else:
            upload_fail += 1
        
        if rid:
            resume_ids.append(rid)
        
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(files)} uploaded (ok={upload_ok} skip={upload_skip} fail={upload_fail})")
    except Exception as e:
        upload_fail += 1
        print(f"  [ERR] {fname}: {str(e)[:80]}")

print(f"Upload done: ok={upload_ok} skip={upload_skip} fail={upload_fail} total={len(resume_ids)}")

print()
print("=" * 60)
print("PHASE 2: Index vectors")
print("=" * 60)

from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index
from src.resume_store.connection import get_mongodb
from src.resume_parser.segmenter import get_segmenter

db = get_mongodb().get_database()
gen = get_embedding_generator()
idx = get_vector_index()
seg = get_segmenter()

all_resumes = list(db["resumes"].find())
print(f"Resumes in MongoDB: {len(all_resumes)}")

indexed = 0
skipped = 0
total_chunks = 0

for ridx, doc in enumerate(all_resumes):
    rid = str(doc.get("resume_id", str(doc.get("_id"))))
    raw = doc.get("raw_text", "")
    pi = doc.get("personal_info", {})
    name = pi.get("full_name", "?") if isinstance(pi, dict) else "?"
    
    if not raw:
        skipped += 1
        continue
    
    # Check if already indexed by looking for existing chunks
    try:
        existing = idx.hybrid_search_small(
            query_dense=[0.001]*1024,
            query_sparse={0: 1.0},
            top_k=1,
            expr='resume_id == "' + rid + '"',
        )
        if existing:
            skipped += 1
            if (ridx + 1) % 20 == 0:
                print(f"  Progress: {ridx+1}/{len(all_resumes)} (indexed={indexed} skipped={skipped})")
            continue
    except:
        pass
    
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
                chunks_list.append(text)
            
            for j, ct in enumerate(chunks_list):
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
                    "metadata": {},
                }]
                idx.insert_chunks(data)
                count += 1
        
        indexed += 1
        total_chunks += count
    except Exception as e:
        print(f"  [ERR] {name} rid={rid[:12]}: {str(e)[:80]}")
    
    if (ridx + 1) % 10 == 0:
        print(f"  Progress: {ridx+1}/{len(all_resumes)} (indexed={indexed} skipped={skipped} chunks={total_chunks})")

# Reload collection
from pymilvus import Collection, connections
from src.common.config import get_settings
s = get_settings()
connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
col = Collection("resume_chunks")
col.release()
col.load()
entities = col.num_entities

print(f"\nIndex done: indexed={indexed} skipped={skipped} chunks={total_chunks} milvus_entities={entities}")
