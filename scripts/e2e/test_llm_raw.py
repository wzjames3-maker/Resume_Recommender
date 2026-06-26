import httpx, json

api_key = "sk-8TOvYUiK72C4yZHF9zfcUwZiWBKrK9aS"
base_url = "https://token.sensenova.cn/v1"

# Test 1: Simple chat (no function call)
print("=== Test 1: Simple Chat ===")
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
payload = {
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好，回复OK"}],
    "temperature": 0.1,
    "max_tokens": 100,
}
resp = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

# Test 2: With function call
print("\n=== Test 2: Function Call ===")
payload2 = {
    "model": "deepseek-v4-flash",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Extract info from: 张三，男，Java开发5年经验"},
    ],
    "functions": [{
        "name": "extract_resume",
        "description": "Extract structured info",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["name"]
        }
    }],
    "function_call": {"name": "extract_resume"},
    "temperature": 0.1,
    "max_tokens": 512,
}
resp2 = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload2, timeout=30)
print(f"Status: {resp2.status_code}")
print(f"Response: {resp2.text[:1000]}")

# Test 3: Without function_call, just with tools format
print("\n=== Test 3: tools format ===")
payload3 = {
    "model": "deepseek-v4-flash",
    "messages": [
        {"role": "system", "content": "你是一个简历解析助手。请以JSON格式返回结果。"},
        {"role": "user", "content": "从以下文本提取姓名和技能（JSON格式）：张三，男，Java开发5年经验，精通Spring Boot"},
    ],
    "temperature": 0.1,
    "max_tokens": 512,
}
resp3 = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload3, timeout=30)
print(f"Status: {resp3.status_code}")
print(f"Response: {resp3.text[:1000]}")
