import httpx, json

BASE = "http://localhost:8000"

resp = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
print(f"Login status: {resp.status_code}")
print(f"Login response: {resp.text[:500]}")

resp2 = httpx.post(f"{BASE}/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
print(f"\nLogin2 status: {resp2.status_code}")
print(f"Login2 response: {resp2.text[:500]}")

resp3 = httpx.get(f"{BASE}/openapi.json")
if resp3.status_code == 200:
    spec = resp3.json()
    paths = list(spec.get("paths", {}).keys())
    print(f"\nAPI Paths ({len(paths)}):")
    for p in paths:
        print(f"  {p}")
else:
    print(f"\nOpenAPI: {resp3.status_code}")
