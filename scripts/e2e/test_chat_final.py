import httpx, json
B = "http://localhost:8000"
r = httpx.post(B+"/api/v1/auth/login", json={"username":"admin","password":"admin123"})
tk = r.json()["token"]
h = {"Authorization": "Bearer "+tk, "Content-Type": "application/json"}
print("=== Chat: Java search ===")
r2 = httpx.post(B+"/api/v1/chat", headers=h, json={"message":"帮我找Java开发经验候选人"}, timeout=120)
msgs = []
for ln in r2.text.strip().split("\n"):
    if ln.strip().startswith("data: "):
        try: msgs.append(json.loads(ln.strip()[6:]))
        except: pass
full = "".join(m.get("content","") for m in msgs if m.get("type")=="token")
errs = [m for m in msgs if m.get("type")=="error"]
if errs:
    print("ERR:", errs[0].get("message","")[:300])
else:
    print("REPLY:", full[:500])
