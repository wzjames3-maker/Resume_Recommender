#!/usr/bin/env python
# coding=utf-8
"""
真实模型渐进式冒烟（C 阶段试点 · 外部模型端到端验证）

用法：
  1) 启动服务：python main.py dev（web）与 python main.py dev celery（worker）
  2) 运行（凭据只走环境变量，不入库）：
     RUN_REAL_MODEL=1 SENSENOVA_API_KEY=... SILICONFLOW_API_KEY=... \
     REAL_MODEL_STAGE=1 uv run python installer/real_model_smoke.py

档位（渐进式，控制时间与调用）：
  REAL_MODEL_STAGE=1  -> 5 份简历   （约 2-3 分钟）
  REAL_MODEL_STAGE=2  -> 30 份简历  （约 8-12 分钟）
  REAL_MODEL_STAGE=3  -> 200 份简历 （约 30-50 分钟，可选）

默认 RUN_REAL_MODEL != 1 时打印 SKIP 退出，不影响 CI。
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

from knowledge.models import Document, Paragraph, State, Status, TaskType  # noqa: E402
from models_provider.tools import get_model_instance_by_model_workspace_id  # noqa: E402

STAGE_SIZES = {"1": 5, "2": 30, "3": 200}
STAGE_QUERY_COUNTS = {"1": 3, "2": 8, "3": 15}
DATASET_JSON = os.path.join(ROOT, "数据集", "train.json")
CORPUS_DIR = os.path.join(ROOT, "testdata", "generated", "resumes")
REPORT_DIR = os.path.join(ROOT, "logs", "real_model_pilot")
WEB = os.environ.get("REAL_MODEL_WEB", "http://127.0.0.1:8080")
WORKSPACE = os.environ.get("REAL_MODEL_WORKSPACE", "workspace-smoke")
USERNAME = os.environ.get("REAL_MODEL_USER", "smoke-admin")
PASSWORD = os.environ.get("REAL_MODEL_PASSWORD", "Smoke@123")
SENSENOVA_BASE = "https://token.sensenova.cn/v1"
SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
HTTP_TIMEOUT = 60

REPORT = {"checks": [], "errors": [], "queries": [], "rerank": [], "chat": []}


def check(name, ok, detail=""):
    REPORT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), name, detail)


def api(method, path, data=None, token=None, files=None):
    url = WEB + path
    headers = {}
    body = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if files is not None:
        boundary = "----maxkb-smoke-%d" % int(time.time() * 1000)
        parts = []
        for field, (filename, content, content_type) in files.items():
            parts.append(("--" + boundary).encode())
            parts.append(
                ("Content-Disposition: form-data; name=\"%s\"; filename=\"%s\"" % (field, filename)).encode()
            )
            parts.append(("Content-Type: %s" % content_type).encode())
            parts.append(b"")
            parts.append(content)
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


def login():
    status, body = api("POST", "/admin/api/user/login", {"username": USERNAME, "password": PASSWORD})
    if status != 200:
        print("登录失败:", status, body)
        print("请先创建用户: uv run python apps/manage.py shell -c \"from users.models.user import User; u=User(username='%s'); u.set_password('%s'); u.save()\"" % (USERNAME, PASSWORD))
        sys.exit(2)
    return body["data"]["token"]


def resume_to_text(record):
    lines = []
    name = record.get("姓名", "")
    if name:
        lines.append("姓名：" + name)
    # 电话为个人联系方式，按 PRD §6 默认不索引，剥离
    edu = record.get("教育经历") or []
    if edu:
        lines.append("")
        lines.append("【教育经历】")
        for item in edu:
            lines.append("- 院校：%s | 学位：%s | 毕业时间：%s" % (
                item.get("毕业院校", ""), item.get("学位", ""), item.get("毕业时间", "")))
    work = record.get("工作经历") or []
    if work:
        lines.append("")
        lines.append("【工作经历】")
        for item in work:
            lines.append("- 时间：%s | 单位：%s | 职务：%s" % (
                item.get("工作时间", ""), item.get("工作单位", ""), item.get("职务", "")))
            content = item.get("工作内容", "")
            if content:
                lines.append("  内容：%s" % content)
    project = record.get("项目经历") or []
    if project:
        lines.append("")
        lines.append("【项目经历】")
        for item in project:
            lines.append("- 项目：%s | 时间：%s" % (item.get("项目名称", ""), item.get("项目时间", "")))
            duty = item.get("项目责任", "")
            if duty:
                lines.append("  职责：%s" % duty)
    return "\n".join(lines)


def synthetic_resume(index):
    schools = ["北京师范大学", "南京大学", "浙江大学", "华中科技大学", "四川大学"]
    majors = ["计算机科学与技术", "软件工程", "电子信息", "自动化", "数学与应用数学"]
    degrees = ["学士学位", "硕士学位"]
    skills = ["Java", "Python", "Go", "前端开发", "数据分析", "机器学习", "数据库", "云计算", "测试开发", "产品设计"]
    duties = [
        "负责核心业务系统设计与开发，主导需求评审与技术方案落地",
        "参与数据平台建设，完成 ETL 流程优化与指标体系建设",
        "负责移动端应用架构与性能优化，推动 CI/CD 流水线落地",
    ]
    return {
        "姓名": "测试候选人%d" % index,
        "教育经历": [{"毕业院校": schools[index % len(schools)], "学位": degrees[index % 2], "毕业时间": "20%02d.06" % (10 + index % 12)}],
        "工作经历": [{
            "工作时间": "2016.07-%s" % ("至今" if index % 2 else "2023.12"),
            "工作单位": "%s科技有限公司" % majors[index % len(majors)],
            "职务": "%s工程师" % skills[index % len(skills)],
            "工作内容": duties[index % len(duties)],
        }],
        "项目经历": [{"项目名称": "%s平台建设项目" % skills[(index + 2) % len(skills)], "项目时间": "2020.01-2021.06", "项目责任": duties[(index + 1) % len(duties)]}],
    }


def build_corpus(size):
    os.makedirs(CORPUS_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(CORPUS_DIR) if f.endswith(".txt"))
    if len(files) >= size:
        return files[:size]
    records = []
    if os.path.exists(DATASET_JSON):
        with open(DATASET_JSON, encoding="utf-8") as f:
            data = json.load(f)
        records = [record for _, record in list(data.items())[:size]]
        source = "数据集/train.json"
    else:
        source = "synthetic"
        for i in range(size):
            records.append(synthetic_resume(i))
    for index, record in enumerate(records):
        filename = "resume_%04d_%s.txt" % (index, (record.get("姓名") or str(index))[:8])
        path = os.path.join(CORPUS_DIR, filename)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(resume_to_text(record))
        if filename not in files:
            files.append(filename)
    files = sorted(files)[:size]
    print("语料: %d 份（来源 %s）-> %s" % (len(files), source, CORPUS_DIR))
    return files


def ensure_model(token, name, model_type, model_name, api_base, api_key, params_form=None):
    status, body = api("GET", "/admin/api/model/%s?name=%s" % (WORKSPACE, urllib.parse.quote(name)), token=token)
    existing = None
    if status == 200 and isinstance(body.get("data"), list):
        for item in body["data"]:
            if item.get("name") == name:
                existing = item
                break
    if existing:
        print("模型已存在:", name, existing.get("id"))
        return existing["id"]
    payload = {
        "name": name,
        "provider": "model_openai_provider",
        "model_type": model_type,
        "model_name": model_name,
        "credential": {"api_base": api_base, "api_key": api_key},
        "model_params_form": params_form or [],
    }
    status, body = api("POST", "/admin/api/model/%s" % WORKSPACE, payload, token=token)
    if status != 200:
        raise RuntimeError("创建模型 %s 失败: %s %s" % (name, status, body))
    model_id = body["data"]["id"]
    print("模型创建成功（真实连通性校验通过）:", name, model_id)
    return model_id


def ensure_knowledge(token, name, embedding_model_id):
    status, body = api("GET", "/admin/api/workspace/%s/knowledge?name=%s" % (WORKSPACE, urllib.parse.quote(name)), token=token)
    existing = None
    if status == 200 and isinstance(body.get("data"), list):
        for item in body["data"]:
            if item.get("name") == name:
                existing = item
                break
    if existing:
        print("知识库已存在:", name, existing.get("id"))
        return existing["id"]
    status, body = api(
        "POST", "/admin/api/workspace/%s/knowledge" % WORKSPACE,
        {"name": name, "folder_id": WORKSPACE, "desc": "简历语义检索试点（脱敏语料）", "embedding_model_id": embedding_model_id},
        token=token,
    )
    if status != 200:
        raise RuntimeError("创建知识库失败: %s %s" % (status, body))
    print("知识库创建成功:", name, body["data"]["id"])
    return body["data"]["id"]


def upload_documents(token, knowledge_id, files):
    exist_names = set(
        QuerySet(Document).filter(knowledge_id=knowledge_id).values_list("name", flat=True)
    )
    uploaded, skipped = [], []
    for filename in files:
        if filename in exist_names:
            skipped.append(filename)
            continue
        with open(os.path.join(CORPUS_DIR, filename), "rb") as f:
            content = f.read()
        status, body = api(
            "POST", "/admin/api/workspace/%s/knowledge/%s/document" % (WORKSPACE, knowledge_id),
            token=token,
            files={"file": (filename, content, "text/plain")},
        )
        if status == 200:
            uploaded.append(filename)
        else:
            detail = body.get("detail") if isinstance(body, dict) else str(body)
            if "exist" in str(detail).lower() or "重复" in str(detail):
                skipped.append(filename)
            else:
                REPORT["errors"].append("上传文档失败 %s: %s %s" % (filename, status, detail))
                print("FAIL 上传文档", filename, status, detail)
    return uploaded, skipped


def wait_embedding(knowledge_id, total, stage):
    deadline = time.time() + {"1": 240, "2": 900, "3": 3600}[stage]
    while time.time() < deadline:
        success = 0
        failed = []
        docs = QuerySet(Document).filter(knowledge_id=knowledge_id)
        for doc in docs:
            state = Status(doc.status)[TaskType.EMBEDDING]
            if state == State.SUCCESS:
                success += 1
            elif state in (State.FAILURE, State.REVOKE, State.REVOKED):
                failed.append(doc.name)
        if success + len(failed) >= total:
            return success, failed
        time.sleep(5)
    docs = QuerySet(Document).filter(knowledge_id=knowledge_id)
    success = sum(1 for d in docs if Status(d.status)[TaskType.EMBEDDING] == State.SUCCESS)
    return success, [d.name for d in docs if Status(d.status)[TaskType.EMBEDDING] != State.SUCCESS]


def hit_test(token, knowledge_id, query, top_number=5):
    status, body = api(
        "POST", "/admin/api/workspace/%s/knowledge/%s/hit_test" % (WORKSPACE, knowledge_id),
        {"query_text": query, "top_number": top_number, "similarity": 0.05, "search_mode": "embedding"},
        token=token,
    )
    if status != 200:
        return []
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data") or data.get("paragraph_list") or []
    return []


def build_queries(knowledge_id, count):
    docs = list(QuerySet(Document).filter(knowledge_id=knowledge_id).order_by("create_time")[:count])
    queries = []
    skills = ["Java", "Python", "Go", "前端", "数据分析", "机器学习", "数据库", "云计算", "测试", "产品", "算法", "运维", "设计"]
    for doc in docs:
        paragraph = QuerySet(Paragraph).filter(document_id=doc.id, is_active=True).order_by("position").first()
        if paragraph is None:
            continue
        text = paragraph.content
        skill = next((kw for kw in skills if kw in text), None)
        query = "擅长%s的候选人简历" % skill if skill else "负责%s的工程师简历" % doc.name[:12]
        queries.append({"query": query, "expected": doc.name})
    return queries


def main():
    if os.environ.get("RUN_REAL_MODEL") != "1":
        print("SKIP: RUN_REAL_MODEL != 1，真实模型冒烟未启用（CI 安全默认）")
        return
    stage = os.environ.get("REAL_MODEL_STAGE", "1")
    size = STAGE_SIZES.get(stage)
    query_count = STAGE_QUERY_COUNTS.get(stage, 3)
    if size is None:
        print("FAIL: 未知 REAL_MODEL_STAGE:", stage)
        sys.exit(2)
    sensenova_key = os.environ.get("SENSENOVA_API_KEY", "")
    siliconflow_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not sensenova_key or not siliconflow_key:
        print("FAIL: 缺少 SENSENOVA_API_KEY 或 SILICONFLOW_API_KEY")
        sys.exit(2)
    print("== 阶段 %s：%d 份简历，%d 条查询 ==" % (stage, size, query_count))
    token = login()
    check("登录", bool(token))
    files = build_corpus(size)
    check("语料准备", len(files) == size)

    llm_id = ensure_model(token, "sensenova-6.8-flash-lite", "LLM", "sensenova-6.8-flash-lite", SENSENOVA_BASE, sensenova_key)
    embedding_id = ensure_model(token, "bge-large-zh-v1.5", "EMBEDDING", "BAAI/bge-large-zh-v1.5", SILICONFLOW_BASE, siliconflow_key,
                                [{"field": "dimensions", "default_value": 1024}])
    rerank_id = ensure_model(token, "bge-reranker-v2-m3", "RERANKER", "BAAI/bge-reranker-v2-m3", SILICONFLOW_BASE, siliconflow_key,
                             [{"field": "top_n", "default_value": 3}])
    check("三个外部模型创建/校验", bool(llm_id and embedding_id and rerank_id))

    kb_name = "简历语义试点S%s" % stage
    knowledge_id = ensure_knowledge(token, kb_name, embedding_id)
    check("知识库创建", bool(knowledge_id))

    uploaded, skipped = upload_documents(token, knowledge_id, files)
    check("文档上传", len(uploaded) + len(skipped) == len(files), "上传%d 跳过%d" % (len(uploaded), len(skipped)))

    success, failed = wait_embedding(knowledge_id, len(files), stage)
    check("向量化完成", success == len(files) and not failed, "成功%d/%d 失败:%s" % (success, len(files), failed[:5]))
    if success == 0:
        print("FAIL: 向量化全部未完成，终止。日志见 logs/。")
        sys.exit(3)

    queries = build_queries(knowledge_id, query_count)
    for item in queries:
        results = hit_test(token, knowledge_id, item["query"], top_number=5)
        names = [str(r.get("document_name") or r.get("name") or "") for r in results]
        hit = item["expected"] in names
        REPORT["queries"].append({"query": item["query"], "expected": item["expected"], "top5": names[:5], "hit": hit})
        check("命中测试[%s]" % item["query"][:18], hit, "期望=%s top1=%s" % (item["expected"], names[:1]))

    rerank_compare(knowledge_id, rerank_id, queries[: min(3, len(queries))])

    chat_verify(token, llm_id, knowledge_id, stage)

    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, "report_s%s.json" % stage)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("报告已写入:", report_path)
    passed = sum(1 for c in REPORT["checks"] if c["ok"])
    print("== 汇总: %d/%d 通过 ==" % (passed, len(REPORT["checks"])))


def rerank_compare(knowledge_id, rerank_model_id, queries):
    if not queries:
        return
    model = get_model_instance_by_model_workspace_id(rerank_model_id, WORKSPACE)
    for item in queries:
        paragraphs = list(QuerySet(Paragraph).filter(knowledge_id=knowledge_id, is_active=True).order_by("?")[:12])
        docs = [p.content[:300] for p in paragraphs]
        try:
            ranked = model.rerank(item["query"], docs, top_n=5)
            REPORT["rerank"].append({"query": item["query"], "rerank_top_indexes": [r["index"] for r in ranked],
                                     "scores": [r["relevance_score"] for r in ranked]})
            check("重排[%s]" % item["query"][:18], len(ranked) > 0, "top5索引=%s" % [r["index"] for r in ranked])
        except Exception as exc:
            REPORT["errors"].append("重排失败 %s: %s" % (item["query"], exc))
            check("重排[%s]" % item["query"][:18], False, str(exc))


def chat_verify(token, llm_model_id, knowledge_id, stage):
    app_name = "简历问答试点S%s" % stage
    status, body = api("GET", "/admin/api/workspace/%s/application?name=%s" % (WORKSPACE, urllib.parse.quote(app_name)), token=token)
    application_id = None
    if status == 200 and isinstance(body.get("data"), list):
        for item in body["data"]:
            if item.get("name") == app_name:
                application_id = item.get("id")
                break
    if application_id is None:
        payload = {
            "name": app_name,
            "desc": "简历语义检索问答试点（脱敏语料）",
            "folder_id": WORKSPACE,
            "model_id": llm_model_id,
            "dialogue_number": 0,
            "prologue": "你好，我是简历检索助手",
            "knowledge_id_list": [knowledge_id],
            "knowledge_setting": {
                "top_n": 3,
                "similarity": 0.05,
                "max_paragraph_char_number": 5000,
                "search_mode": "embedding",
                "no_references_setting": {"status": "ai_questioning", "value": "知识库未命中，请直接回答：{question}"},
            },
            "model_setting": {
                "prompt": "请基于知识库内容回答，如无相关内容请明确说明。",
                "system": "",
                "no_references_prompt": "{question}",
                "reasoning_content_enable": False,
            },
            "problem_optimization": False,
            "problem_optimization_prompt": "optimize",
            "type": "SIMPLE",
        }
        status, body = api("POST", "/admin/api/workspace/%s/application" % WORKSPACE, payload, token=token)
        if status != 200:
            REPORT["errors"].append("创建应用失败: %s %s" % (status, body))
            check("应用创建", False, str(body)[:200])
            return
        application_id = body["data"]["id"]
    check("应用创建/复用", bool(application_id))
    query = REPORT["queries"][0]["query"] if REPORT["queries"] else "有Java经验的候选人简历"
    status, body = api("POST", "/admin/api/workspace/%s/application/%s/chat" % (WORKSPACE, application_id),
                       {"message": query, "stream": False, "re_chat": False, "chat_record_id": None}, token=token)
    data = body.get("data") if isinstance(body, dict) else None
    if status == 200 and isinstance(data, dict):
        answer = data.get("answer_text") or data.get("content") or ""
        citation = data.get("citation_list") or data.get("paragraph_list") or []
        REPORT["chat"].append({"query": query, "answer": answer[:200], "citation_count": len(citation)})
        check("问答链路（LLM 引用）", bool(answer) and len(citation) > 0, "回答%d字 引用%d条" % (len(answer), len(citation)))
    else:
        REPORT["errors"].append("问答失败: %s %s" % (status, body))
        check("问答链路（LLM 引用）", False, str(body)[:200])


if __name__ == "__main__":
    main()
