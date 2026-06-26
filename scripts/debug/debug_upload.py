import httpx, json, os

BASE = "http://localhost:8000"

# Login
resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = resp.json()["token"]
auth = {"Authorization": "Bearer " + token}
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

# Upload zhangsan resume
print("=== Upload zhangsan.json ===")
with open("test_resumes/zhangsan.json", "r", encoding="utf-8") as f:
    rd = f.read()
files = {"file": ("zhangsan.json", rd, "application/json")}
resp = httpx.post(BASE + "/api/v1/resumes/upload", headers=auth, files=files, timeout=120)
print("Status:", resp.status_code)
print("Response:", resp.text[:500])

# Check if collection exists now in Milvus
print("\n=== Check Milvus collections ===")
from pymilvus import connections, utility
connections.connect(alias="default", uri="http://milvus-standalone:19530")
cols = utility.list_collections()
print("Collections:", cols)
connections.disconnect("default")

# Wait a bit for indexing
import time
time.sleep(3)

# Try chat search again
print("\n=== Chat: Java search (after upload) ===")
resp2 = httpx.post(BASE + "/api/v1/chat", headers=headers, json={"message": "帮我找Java开发"}, timeout=120)
print("Status:", resp2.status_code)
print("Raw:", resp2.text[:2000])
