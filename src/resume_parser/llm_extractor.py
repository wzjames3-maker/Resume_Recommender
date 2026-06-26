"""
智能招聘 RAG 推荐系统 - LLM 结构化提取模块
使用 prompt-based JSON extraction（不依赖 function_call）
"""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

from src.common.config import get_settings
from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.resume_store.models import (
    EducationEntry, ExperienceEntry, PersonalInfo,
    ProjectEntry, SkillEntry,
)

logger = get_logger("llm_extractor")

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 0
RETRY_DELAY = 2


class ExtractionWarning(BaseModel):
    field: str = Field(...)
    message: str = Field(...)
    confidence: float = Field(default=1.0)


class ExtractionMetrics(BaseModel):
    input_tokens: int = Field(0)
    output_tokens: int = Field(0)
    total_tokens: int = Field(0)
    duration_ms: int = Field(0)
    retry_count: int = Field(0)


class ResumeStructured(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education_list: List[EducationEntry] = Field(default_factory=list)
    experience_list: List[ExperienceEntry] = Field(default_factory=list)
    project_list: List[ProjectEntry] = Field(default_factory=list)
    skill_list: List[SkillEntry] = Field(default_factory=list)
    extraction_warnings: List[ExtractionWarning] = Field(default_factory=list)
    confidence_score: float = Field(default=1.0, ge=0, le=1)


_EXTRACT_JSON_SCHEMA = """{
  "personal_info": {
    "full_name": "姓名", "phone": "手机号", "email": "邮箱",
    "city": "城市", "birth_year": 1990, "gender": "男/女",
    "years_of_experience": 5, "current_company": "公司",
    "current_title": "职位", "summary": "简介"
  },
  "education_list": [
    {"school": "学校", "degree": "学历", "major": "专业",
     "start_date": "2012-09", "end_date": "2016-06",
     "is_985": true, "is_211": true}
  ],
  "experience_list": [
    {"company": "公司", "title": "职位",
     "start_date": "2016-07", "end_date": "2021-12",
     "is_current": false, "description": "描述", "achievements": ["成就"]}
  ],
  "project_list": [
    {"name": "项目名", "role": "角色",
     "start_date": "2018-01", "end_date": "2019-06",
     "description": "描述", "tech_stack": ["技术"]}
  ],
  "skill_list": [
    {"name": "技能名", "proficiency": "精通/熟练/了解", "years_of_experience": 3, "category": "分类"}
  ],
  "confidence_score": 0.8
}"""


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """从 LLM 响应文本中提取 JSON 对象"""
    # Try ```json ... ``` block
    match = re.search(r"`{3}(?:json)?\s*(\{.*?\})\s*`{3}", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        return json.loads(text[first:last + 1])
    raise ValueError(f"Cannot parse JSON from: {text[:300]}")


class LLMExtractor:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.llm.LLM_API_KEY
        self.api_base_url = settings.llm.LLM_BASE_URL
        self.model = settings.llm.LLM_MODEL
        self.timeout = DEFAULT_TIMEOUT

    def extract(self, text: str) -> ResumeStructured:
        start = time.time()
        prompt = self._build_prompt(text)
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw, metrics = self._call_llm(prompt)
                structured = self._parse(raw)
                metrics.duration_ms = int((time.time() - start) * 1000)
                logger.info(f"LLM extract done {metrics.duration_ms}ms tokens={metrics.total_tokens}")
                return structured
            except Exception as exc:
                logger.warning(f"LLM extract attempt {attempt+1} failed: {exc}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    return self._fallback(str(exc))
        return self._fallback("exhausted")

    def _build_prompt(self, text: str) -> str:
        return (
            "请从以下简历文本中提取结构化信息。\n"
            "要求：\n"
            "1. 只输出一个合法的JSON对象，不要输出其他文字\n"
            "2. key必须用英文，严格按照schema\n"
            "3. 不存在的字段用null或空数组\n\n"
            f"JSON Schema:\n{_EXTRACT_JSON_SCHEMA}\n\n"
            f"简历文本:\n{text}"
        )

    def _call_llm(self, prompt: str) -> Tuple[Dict[str, Any], ExtractionMetrics]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是简历解析助手，只输出合法JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(f"{self.api_base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY)
                        continue
                    raise ExternalServiceError(error_code=ErrorCode.SYS_005, detail=f"LLM {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                usage = data.get("usage", {})
                metrics = ExtractionMetrics(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                )
                msg = data["choices"][0]["message"]
                # Try function_call first (models that support it)
                fc = msg.get("function_call")
                if fc and fc.get("arguments"):
                    return json.loads(fc["arguments"]), metrics
                content = msg.get("content", "{}")
                arguments = _extract_json_from_text(content)
                return arguments, metrics
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                raise ExternalServiceError(error_code=ErrorCode.SYS_005, detail=str(exc))
            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                raise ExternalServiceError(error_code=ErrorCode.SYS_004, detail="timeout")
            except ExternalServiceError:
                raise
            except Exception as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                raise ExternalServiceError(error_code=ErrorCode.SYS_005, detail=str(exc))
        return {}, ExtractionMetrics()

    def _parse(self, raw: Dict[str, Any]) -> ResumeStructured:
        pi = PersonalInfo(**raw.get("personal_info", {}))
        edus = [EducationEntry(**e) for e in raw.get("education_list", [])]
        exps = [ExperienceEntry(**e) for e in raw.get("experience_list", [])]
        projs = [ProjectEntry(**p) for p in raw.get("project_list", [])]
        skills = [SkillEntry(**{("years_of_experience" if k == "years" else "proficiency" if k == "level" else k): v for k, v in s.items()}) for s in raw.get("skill_list", [])]
        return ResumeStructured(
            personal_info=pi, education_list=edus, experience_list=exps,
            project_list=projs, skill_list=skills,
            confidence_score=raw.get("confidence_score", 0.8),
        )

    def _fallback(self, msg: str) -> ResumeStructured:
        return ResumeStructured(
            personal_info=PersonalInfo(),
            extraction_warnings=[ExtractionWarning(field="all", message=f"fallback: {msg}", confidence=0.0)],
            confidence_score=0.0,
        )


llm_extractor = LLMExtractor()


def get_llm_extractor() -> LLMExtractor:
    return llm_extractor
