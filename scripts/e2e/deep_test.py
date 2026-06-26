"""
深度测试: 15个搜索场景 x 100+简历库
"""
import json
import time
import requests

API_BASE = "http://localhost:8000"

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
        resp = requests.post(f"{API_BASE}/api/search", json={"query": query, "top_k": 5}, timeout=60)
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("results", data.get("candidates", []))
            count = len(candidates)
            print(f"  ✅ 成功 | 耗时: {elapsed:.2f}s | 返回: {count}条")
            for j, c in enumerate(candidates[:3]):
                name = c.get("name", c.get("metadata", {}).get("name", "?"))
                score = c.get("score", c.get("rerank_score", "?"))
                print(f"     {j+1}. {name} (score: {score})")
            results.append({"label": label, "query": query, "status": "OK", "time": round(elapsed, 2), "count": count, "top3": [{"name": c.get("name", c.get("metadata", {}).get("name", "?")), "score": c.get("score", c.get("rerank_score", "?"))} for c in candidates[:3]]})
        else:
            elapsed = time.time() - start
            print(f"  ❌ HTTP {resp.status_code} | 耗时: {elapsed:.2f}s")
            print(f"     {resp.text[:200]}")
            results.append({"label": label, "query": query, "status": f"HTTP_{resp.status_code}", "time": round(elapsed, 2), "error": resp.text[:200]})
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ❌ 异常: {str(e)[:100]} | 耗时: {elapsed:.2f}s")
        results.append({"label": label, "query": query, "status": "ERROR", "time": round(elapsed, 2), "error": str(e)[:200]})

# Summary
print("\n" + "=" * 70)
print("测试汇总")
print("=" * 70)
ok_count = sum(1 for r in results if r["status"] == "OK")
fail_count = len(results) - ok_count
avg_time = sum(r["time"] for r in results) / len(results) if results else 0
print(f"总查询: {len(results)}")
print(f"成功: {ok_count} | 失败: {fail_count}")
print(f"平均耗时: {avg_time:.2f}s")

# Save results
with open("test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\n结果已保存到 test_results.json")
