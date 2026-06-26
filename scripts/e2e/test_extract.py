"""
Test LLM extraction directly
"""
import json
from src.resume_parser.llm_extractor import get_llm_extractor

extractor = get_llm_extractor()
print(f"Model: {extractor.model}")
print(f"API Base: {extractor.api_base_url}")

# Test with a sample resume text
sample = json.dumps({
    "name": "张三",
    "gender": "男",
    "birth_year": 1995,
    "phone": "13800138000",
    "email": "zhangsan@example.com",
    "education": [{"school": "清华大学", "degree": "本科", "major": "计算机科学", "start": "2013", "end": "2017"}],
    "experience": [{"company": "腾讯", "title": "高级Java工程师", "duration": "2017.07-至今", "description": "负责微信支付核心系统开发"}],
    "skills": ["Java", "Spring Boot", "MySQL", "Redis", "Docker"]
}, ensure_ascii=False)

print("\nTesting extraction...")
result = extractor.extract(sample)
print(f"Result type: {type(result)}")
print(f"personal_info.full_name: {result.personal_info.full_name}")
print(f"personal_info.current_company: {result.personal_info.current_company}")
print(f"skills count: {len(result.skill_list)}")
print(f"education count: {len(result.education_list)}")
print(f"experience count: {len(result.experience_list)}")
print(f"confidence: {result.confidence_score}")
