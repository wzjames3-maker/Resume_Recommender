import httpx, json, os

BASE = "http://localhost:8000"
results = {}

def test(name, fn):
    try:
        r = fn()
        results[name] = ("PASS", str(r)[:500])
        print("[PASS] " + name + ": " + str(r)[:200])
    except Exception as e:
        results[name] = ("FAIL", str(e)[:200])
        print("[FAIL] " + name + ": " + str(e)[:200])

def parse_sse(text):
    """Parse SSE stream into list of messages"""
    msgs = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                msgs.append(data)
            except:
                pass
    return msgs

def t_login():
    resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    data = resp.json()
    assert resp.status_code == 200 and data.get("token")
    return data["token"]

test("1. Login", t_login)
token = t_login()
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
auth = {"Authorization": "Bearer " + token}

def t_chat():
    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "你好",
    }, timeout=120)
    assert resp.status_code == 200
    msgs = parse_sse(resp.text)
    full = "".join(m.get("content", "") for m in msgs if m.get("type") == "token")
    done = [m for m in msgs if m.get("type") == "done"]
    return "msgs=" + str(len(msgs)) + " done=" + str(len(done)) > 0 + " reply=" + full[:100]

test("2. Chat SSE", t_chat)

def t_chat_intent():
    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "帮我找一个有Java开发经验的候选人",
    }, timeout=120)
    assert resp.status_code == 200
    msgs = parse_sse(resp.text)
    full = "".join(m.get("content", "") for m in msgs if m.get("type") == "token")
    return "reply=" + full[:200]

test("3. Chat Intent Search", t_chat_intent)

def t_upload():
    rp = "test_resumes/zhangsan.json"
    if not os.path.exists(rp):
        return "skip"
    with open(rp, "r", encoding="utf-8") as f:
        rd = f.read()
    files = {"file": ("zhangsan.json", rd, "application/json")}
    resp = httpx.post(BASE + "/api/v1/resumes/upload", headers=auth, files=files, timeout=120)
    assert resp.status_code in (200, 201, 409)
    return "status=" + str(resp.status_code)

test("4. Upload Resume", t_upload)

def t_conversations():
    resp = httpx.get(BASE + "/api/v1/conversations", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    count = len(data.get("items", []))
    return "conversations=" + str(count)

test("5. List Conversations", t_conversations)

def t_search():
    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "推荐有字节跳动工作经验的候选人",
    }, timeout=120)
    assert resp.status_code == 200
    msgs = parse_sse(resp.text)
    full = "".join(m.get("content", "") for m in msgs if m.get("type") == "token")
    return "reply=" + full[:200]

test("6. Search After Upload", t_search)

print()
print("=" * 60)
passed = sum(1 for v in results.values() if v[0] == "PASS")
print("E2E RESULT: " + str(passed) + "/" + str(len(results)) + " PASS")
print("=" * 60)
