"""
检查候选人返回数据结构 + 修复 name 显示
"""
import json
import requests

API_BASE = "http://localhost:8000"
login_resp = requests.post(f"{API_BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123"}, timeout=10)
TOKEN = login_resp.json()["token"]
headers = {"Authorization": f"Bearer {TOKEN}"}

# Single query to inspect candidate data structure
resp = requests.post(
    f"{API_BASE}/api/v1/chat",
    json={"message": "帮我找一个有Java开发经验的候选人"},
    headers=headers,
    timeout=120,
    stream=True
)

candidates = []
full_text = ""
for line in resp.iter_lines(decode_unicode=True):
    if not line or not line.startswith("data: "):
        continue
    data_str = line[6:]
    try:
        data = json.loads(data_str)
    except:
        continue
    evt_type = data.get("type", "")
    if evt_type == "sources":
        candidates = data.get("candidates", [])
    elif evt_type == "token":
        full_text += data.get("content", "")

print(f"Candidates count: {len(candidates)}")
print(f"\nFirst candidate full structure:")
if candidates:
    print(json.dumps(candidates[0], ensure_ascii=False, indent=2))
    print(f"\nAll candidate keys: {list(candidates[0].keys())}")
    # Check top-level name vs metadata.name
    for i, c in enumerate(candidates[:3]):
        print(f"\nCandidate {i+1}:")
        print(f"  top-level name: {c.get('name', 'MISSING')}")
        print(f"  metadata.name: {c.get('metadata', {}).get('name', 'MISSING')}")
        print(f"  resume_id: {c.get('resume_id', 'MISSING')}")
        print(f"  score: {c.get('score', 'MISSING')}")

print(f"\nLLM text preview: {full_text[:300]}")
