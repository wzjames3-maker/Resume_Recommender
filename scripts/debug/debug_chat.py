import httpx, json
BASE = "http://localhost:8000"

resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = resp.json()["token"]
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

print("=== Chat: 你好 ===")
resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={"message": "你好"}, timeout=120)
print("Status:", resp.status_code)
print("Raw response (first 2000 chars):")
print(repr(resp.text[:2000]))

print("\n=== Chat: Java search ===")
resp2 = httpx.post(BASE + "/api/v1/chat", headers=headers, json={"message": "帮我找Java开发"}, timeout=120)
print("Status:", resp2.status_code)
print("Raw response (first 3000 chars):")
print(repr(resp2.text[:3000]))
