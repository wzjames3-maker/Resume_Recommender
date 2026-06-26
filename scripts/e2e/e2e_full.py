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

def t_login():
    resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    data = resp.json()
    assert resp.status_code == 200
    assert data.get("token")
    return data["token"]

test("1. Login", t_login)
token = t_login()
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
auth = {"Authorization": "Bearer " + token}

def t_chat():
    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "帮我找一个有Java开发经验的候选人",
    }, timeout=120)
    assert resp.status_code == 200, "chat " + str(resp.status_code) + ": " + resp.text[:200]
    data = resp.json()
    msg = data.get("message", data.get("response", ""))
    intent = data.get("intent", "unknown")
    return "intent=" + str(intent) + " msg=" + str(msg)[:150]

test("2. Chat", t_chat)

def t_conversation():
    resp = httpx.post(BASE + "/api/v1/conversations", headers=headers, json={
        "title": "E2E Test"
    }, timeout=30)
    assert resp.status_code == 200, "conv " + str(resp.status_code)
    data = resp.json()
    cid = data.get("id", data.get("conversation_id", "?"))
    return "conv_id=" + str(cid)

test("3. Conversation", t_conversation)

def t_upload():
    rp = "test_resumes/zhangsan.json"
    if not os.path.exists(rp):
        return "skip"
    with open(rp, "r", encoding="utf-8") as f:
        rd = f.read()
    files = {"file": ("zhangsan.json", rd, "application/json")}
    resp = httpx.post(BASE + "/api/v1/resumes/upload", headers=auth, files=files, timeout=120)
    assert resp.status_code in (200, 201, 409), "upload " + str(resp.status_code) + ": " + resp.text[:200]
    return "status=" + str(resp.status_code) + " resp=" + json.dumps(resp.json(), ensure_ascii=False)[:200]

test("4. Upload", t_upload)

def t_search():
    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "推荐有字节跳动工作经验的候选人",
    }, timeout=120)
    assert resp.status_code == 200
    data = resp.json()
    msg = data.get("message", data.get("response", ""))
    return "msg=" + str(msg)[:200]

test("5. Search After Upload", t_search)

print()
print("=" * 60)
passed = sum(1 for v in results.values() if v[0] == "PASS")
print("E2E RESULT: " + str(passed) + "/" + str(len(results)) + " PASS")
print("=" * 60)
