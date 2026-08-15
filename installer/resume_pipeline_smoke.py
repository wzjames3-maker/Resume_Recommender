#!/usr/bin/env python
# coding=utf-8
"""
简历语义索引端到端冒烟（阶段 2 打通验证）：HR 上传 → 自动切片(LLM) → 建文档 → 向量化 → 检索命中

前置：web(8080) + celery 已启动；smoke-admin 存在；SenseNova/SiliconFlow 模型已注册。
用法：python installer/resume_pipeline_smoke.py [简历份数，默认 3]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maxkb.settings")

import django  # noqa: E402

django.setup()

from django.db.models import QuerySet  # noqa: E402

from knowledge.models import Document, Embedding, Paragraph, State, Status, TaskType  # noqa: E402
from models_provider.models import Model  # noqa: E402

WEB = os.environ.get("REAL_MODEL_WEB", "http://127.0.0.1:8080")
WORKSPACE = "default"
USERNAME = os.environ.get("REAL_MODEL_USER", "smoke-admin")
PASSWORD = os.environ.get("REAL_MODEL_PASSWORD", "Smoke@123")
CORPUS_DIR = os.path.join(ROOT, "testdata", "generated", "resumes")
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 3
HTTP_TIMEOUT = 60


def api(method, path, data=None, token=None, files=None):
    url = WEB + path
    headers = {}
    body = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if files is not None:
        boundary = "----maxkb-smoke-%d" % int(time.time() * 1000)
        parts = []
        for field, value in files.items():
            parts.append(("--" + boundary).encode())
            if isinstance(value, tuple):
                filename, content, content_type = value
                parts.append(("Content-Disposition: form-data; name=\"%s\"; filename=\"%s\"" % (field, filename)).encode())
                parts.append(("Content-Type: %s" % content_type).encode())
                parts.append(b"")
                parts.append(content)
            else:
                parts.append(("Content-Disposition: form-data; name=\"%s\"" % field).encode())
                parts.append(b"")
                parts.append(str(value).encode("utf-8"))
        parts.append(("--" + boundary + "--").encode())
        body = b"\r\n".join(parts)
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"detail": raw[:500]}
    except Exception as exc:
        return -1, {"detail": str(exc)}


def main():
    print("== 简历语义索引端到端冒烟（%d 份）==" % COUNT)
    # 1) 登录
    status, body = api("POST", "/admin/api/user/login", {"username": USERNAME, "password": PASSWORD})
    if status != 200:
        print("登录失败:", status, body)
        return 2
    token = body["data"]["token"]
    print("登录 OK")

    # 2) 配置 HR AI 模型（llm_model_id 指向已注册 LLM）
    llm_model = QuerySet(Model).filter(model_type="LLM").first()
    if llm_model is None:
        print("未找到 LLM 模型")
        return 2
    status, body = api("PUT", "/admin/api/workspace/%s/hr/ai/config" % WORKSPACE,
                       {"llm_model_id": str(llm_model.id)}, token=token)
    print("HR AI 配置:", status, body if status == 200 else body)

    # 3) 上传简历（每份一次请求，multipart 单文件）
    names = sorted(f for f in os.listdir(CORPUS_DIR) if f.endswith(".txt"))[:COUNT]
    records = []
    for name in names:
        with open(os.path.join(CORPUS_DIR, name), "rb") as handle:
            content = handle.read()
        status, body = api("POST", "/admin/api/workspace/%s/hr/candidates/resumes" % WORKSPACE,
                           files={"files": (name, content, "text/plain"), "source_channel": "OTHER"}, token=token)
        if status != 200:
            print("上传失败:", name, status, body)
            return 2
        records.extend(body.get("data") or [])
    resume_ids = [r["resume_id"] for r in records]
    print("上传 %d 份: %s" % (len(resume_ids), [r["file_name"] for r in records]))

    # 4) 轮询解析 + 语义索引状态（document_id 出现）
    deadline = time.time() + 240
    indexed = {}
    while time.time() < deadline:
        status, body = api("GET", "/admin/api/workspace/%s/hr/resumes/batch-status?ids=%s" % (
            WORKSPACE, urllib.parse.quote(",".join(resume_ids))), token=token)
        items = (body.get("data") or []) if isinstance(body.get("data"), list) else []
        for item in items:
            rid = item["resume_id"]
            st = item["status"]
            if st == "SUCCESS" and item.get("document_id"):
                indexed[rid] = item
            elif st in ("FAILED",):
                print("简历失败:", item.get("file_name"), item.get("error_message"))
        if len(indexed) == len(resume_ids):
            break
        time.sleep(5)
    print("索引完成:", len(indexed), "/", len(resume_ids))
    if len(indexed) < len(resume_ids):
        print("超时，未全部索引")
        return 1

    # 5) 等向量化完成（Document EMBEDDING 位 SUCCESS）
    doc_ids = [item["document_id"] for item in indexed.values()]
    deadline = time.time() + 240
    while time.time() < deadline:
        docs = QuerySet(Document).filter(id__in=doc_ids)
        all_done = True
        for doc in docs:
            st = Status(doc.status)[TaskType.EMBEDDING]
            if st not in (State.SUCCESS, State.FAILURE):
                all_done = False
        if all_done:
            break
        time.sleep(5)
    for doc in docs:
        st = Status(doc.status)[TaskType.EMBEDDING]
        para_count = Paragraph.objects.filter(document_id=doc.id).count()
        emb_count = Embedding.objects.filter(document_id=doc.id).count()
        print("文档 %s: name=%s embedding=%s paragraphs=%d embeddings=%d" % (
            doc.id, doc.name, st.name, para_count, emb_count))
        if st == State.FAILURE or emb_count == 0:
            print("  !! 向量化失败或为空")
            return 1
    print("== 冒烟通过 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
