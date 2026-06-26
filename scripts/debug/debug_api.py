import httpx, json
BASE = "http://localhost:8000"

resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = resp.json()["token"]
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

# Check chat endpoint raw response
print("=== Chat raw ===")
resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
    "message": "你好"
}, timeout=120)
print("Status:", resp.status_code)
print("Headers:", dict(resp.headers))
print("Body:", repr(resp.text[:500]))

# Try conversation endpoints
print("\n=== Conversations ===")
resp2 = httpx.get(BASE + "/api/v1/conversations", headers=headers)
print("Status:", resp2.status_code)
print("Body:", resp2.text[:500])

# Check what the chat endpoint expects
print("\n=== OpenAPI spec for /api/v1/chat ===")
resp3 = httpx.get(BASE + "/openapi.json")
spec = resp3.json()
chat_path = spec.get("paths", {}).get("/api/v1/chat", {})
print(json.dumps(chat_path, ensure_ascii=False, indent=2)[:2000])
