"""
深度测试: 15个搜索场景 x 100+简历库
使用 /api/v1/chat SSE 端点
"""
import json
import time
import requests

API_BASE = "http://localhost:8000"

# 1. Login
print("登录中...")
login_resp = requests.post(f"{API_BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123"}, timeout=10)
login_data = login_resp.json()
TOKEN = login_data["token"]
print(f"登录成功: user_id={login_data['user_id']}, role={login_data['role']}")

headers = {"Authorization": f"Bearer {TOKEN}"}

search_queries = [
    ("Java开发经验", "帮我找一个有Java开发经验的候选人"),
    ("前端开发工程师", "推荐前端开发工程师"),
    ("AI算法工程师", "有没有AI算法工程师"),
    ("DevOps运维", "需要DevOps运维工程师"),
    ("产品经理", "找产品经理"),
    ("腾讯工作经验", "有腾讯工作经验的人"),
    ("Docker/K8s", "会Docker和Kubernetes的"),
    ("清华大学", "清华大学毕业的"),
    ("3年后端", "需要3年以上经验的后端工程师"),
    ("Rust系统编程", "找会Rust的系统编程工程师"),
    ("iOS开发", "有没有做iOS开发的"),
    ("数据科学家", "推荐数据科学家"),
    ("安全工程师", "需要安全工程师"),
    ("Go语言", "找Go语言开发"),
    ("测试工程师", "有没有测试工程师"),
]

results = []
print("=" * 70)
print("智能招聘 RAG 系统 - 15场景深度测试")
print("=" * 70)

for i, (label, query) in enumerate(search_queries, 1):
    print(f"\n[{i:2d}/15] 测试: {label}")
    print(f"  查询: {query}")
    start = time.time()
    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/chat",
            json={"message": query},
            headers=headers,
            timeout=120,
            stream=True
        )
        elapsed = time.time() - start
        
        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code} | 耗时: {elapsed:.2f}s")
            print(f"     {resp.text[:300]}")
            results.append({"label": label, "status": f"HTTP_{resp.status_code}", "time": round(elapsed, 2)})
            continue
        
        # Parse SSE stream
        full_text = ""
        candidates = []
        session_id = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            try:
                data = json.loads(data_str)
            except:
                continue
            evt_type = data.get("type", "")
            if evt_type == "token":
                full_text += data.get("content", "")
            elif evt_type == "sources":
                candidates = data.get("candidates", [])
            elif evt_type == "done":
                session_id = data.get("session_id")
            elif evt_type == "error":
                full_text = f"ERROR: {data.get('message', '')}"
        
        elapsed = time.time() - start
        count = len(candidates)
        
        if count > 0:
            print(f"  ✅ 成功 | 耗时: {elapsed:.2f}s | 候选人: {count}条")
            for j, c in enumerate(candidates[:3]):
                name = c.get("name", c.get("metadata", {}).get("name", "?"))
                score = c.get("score", c.get("rerank_score", "?"))
                print(f"     {j+1}. {name} (score: {score})")
            results.append({"label": label, "query": query, "status": "OK", "time": round(elapsed, 2), "count": count, "top3": [{"name": c.get("name", "?"), "score": c.get("score", "?")} for c in candidates[:3]], "text_preview": full_text[:100]})
        elif full_text:
            print(f"  ⚠️ 有响应但无候选人 | 耗时: {elapsed:.2f}s")
            print(f"     回复: {full_text[:150]}")
            results.append({"label": label, "query": query, "status": "NO_CANDIDATES", "time": round(elapsed, 2), "text": full_text[:200]})
        else:
            print(f"  ❌ 空响应 | 耗时: {elapsed:.2f}s")
            results.append({"label": label, "query": query, "status": "EMPTY", "time": round(elapsed, 2)})
            
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ❌ 异常: {str(e)[:100]} | 耗时: {elapsed:.2f}s")
        results.append({"label": label, "query": query, "status": "ERROR", "time": round(elapsed, 2), "error": str(e)[:200]})

# Summary
print("\n" + "=" * 70)
print("测试汇总")
print("=" * 70)
ok = sum(1 for r in results if r["status"] == "OK")
no_cand = sum(1 for r in results if r["status"] == "NO_CANDIDATES")
fail = sum(1 for r in results if r["status"] not in ("OK", "NO_CANDIDATES"))
avg_time = sum(r["time"] for r in results) / len(results) if results else 0
print(f"总查询: {len(results)}")
print(f"✅ 成功(有候选人): {ok}")
print(f"⚠️ 有回复无候选人: {no_cand}")
print(f"❌ 失败: {fail}")
print(f"平均耗时: {avg_time:.2f}s")

with open("deep_test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\n结果已保存到 deep_test_results.json")
