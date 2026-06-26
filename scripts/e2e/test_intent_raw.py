import httpx, json

api_key = "sk-8TOvYUiK72C4yZHF9zfcUwZiWBKrK9aS"
base_url = "https://token.sensenova.cn/v1"

headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

function_schema = {
    "name": "classify_intent",
    "description": "Classify user intent",
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["recruitment.search", "recruitment.refine", "candidate.lookup", "resume.upload", "chat", "fallback"]},
            "confidence": {"type": "number"},
            "candidate_slots": {"type": "object", "properties": {"skills": {"type": "array", "items": {"type": "string"}}}},
            "query_slots": {"type": "object", "properties": {"raw_keywords": {"type": "array", "items": {"type": "string"}}}},
            "reasoning": {"type": "string"},
        },
        "required": ["intent", "confidence"],
    },
}

payload = {
    "model": "deepseek-v4-flash",
    "messages": [
        {"role": "system", "content": "You are an intent classifier."},
        {"role": "user", "content": "帮我找一个有Java经验的候选人"},
    ],
    "functions": [function_schema],
    "function_call": {"name": "classify_intent"},
    "temperature": 0.1,
    "max_tokens": 2048,
}

resp = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:2000]}")
