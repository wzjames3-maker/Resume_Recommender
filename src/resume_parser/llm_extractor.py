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

DEFAULT_TIMEOUT = 300
MAX_RETRIES = 2
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
    "city": "城市", "gender": "男",
    "years_of_experience": 5, "current_company": "公司",
    "current_title": "职位", "summary": "简介"
  },
  "education_list": [
    {"school": "学校", "degree": "本科", "major": "专业",
     "start_date": "2012-09", "end_date": "2016-06"}
  ],
  "experience_list": [
    {"company": "公司", "title": "职位",
     "start_date": "2016-07", "end_date": "2021-12",
     "description": "职责描述"}
  ],
  "skill_list": [
    {"name": "Python"}, {"name": "Java"}, {"name": "MySQL"}
  ],
  "confidence_score": 0.8
}"""

_SKILL_EXTRACT_PROMPT = """从以下简历文本中提取所有技能名称。
技能包括: 编程语言、框架、数据库、工具、设计软件、办公软件、语言能力等。
只输出JSON数组，如: ["Python", "Java", "MySQL", "Photoshop", "英语六级"]

简历文本:
{text}"""


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """从 LLM 响应文本中提取 JSON 对象或数组"""
    match = re.search(r"`{3}(?:json)?\s*(\[.*?\]|\{.*?\})\s*`{3}", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    for prefix, suffix in [("{", "}"), ("[", "]")]:
        first = text.find(prefix)
        last = text.rfind(suffix)
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
        prompts = [self._build_simple_prompt(text), self._build_structured_prompt(text)]
        for attempt in range(MAX_RETRIES + 1):
            prompt_idx = min(attempt, len(prompts) - 1)
            prompt = prompts[prompt_idx]
            try:
                raw, metrics = self._call_llm(prompt)
                structured = self._parse(raw)
                if self._is_empty_result(structured):
                    if attempt < MAX_RETRIES:
                        logger.info(f"Prompt {prompt_idx} 返回空，切换重试...")
                        time.sleep(RETRY_DELAY)
                        continue
                    return self._fallback("all attempts returned empty")
                metrics.duration_ms = int((time.time() - start) * 1000)
                logger.info(f"LLM extract done {metrics.duration_ms}ms tokens={metrics.total_tokens}")
                if not structured.skill_list:
                    logger.info("技能为空，专项提取中...")
                    structured.skill_list = self._extract_skills(text)
                return structured
            except Exception as exc:
                logger.warning(f"LLM extract attempt {prompt_idx} failed: {exc}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    return self._fallback(str(exc))
        return self._fallback("exhausted")

    def _extract_skills(self, text: str) -> List[SkillEntry]:
        """专项技能提取（当主提取无技能时使用）"""
        try:
            prompt = _SKILL_EXTRACT_PROMPT.format(text=text[:2000])
            raw, _ = self._call_llm(prompt)
            logger.info(f"技能提取返回: type={type(raw).__name__}, val={str(raw)[:150]}")
            names = raw if isinstance(raw, list) else raw.get("skills", raw.get("skill_list", []))
            if names and isinstance(names, list):
                result = [SkillEntry(name=str(n)) for n in names if str(n).strip()]
                logger.info(f"技能提取成功: {len(result)} 个")
                return result
            logger.warning(f"技能提取失败, raw={str(raw)[:100]}")
        except Exception as exc:
            logger.warning(f"技能提取异常: {type(exc).__name__}: {exc}")
        return []

    @staticmethod
    def _is_empty_result(structured: ResumeStructured) -> bool:
        return (not structured.education_list
                and not structured.experience_list
                and not structured.project_list
                and not structured.skill_list
                and not structured.personal_info.full_name)

    def _build_simple_prompt(self, text: str) -> str:
        return (
            "解析简历，输出JSON（无其他文字）。\n"
            "格式: {\"name\":\"姓名\",\"education\":[\"学校 学历 专业\"],"
            "\"experience\":[\"公司 职位 时间段 职责\"],"
            "\"skills\":[\"技能1\",\"技能2\"]}\n\n"
            f"简历:\n{text}"
        )

    def _build_structured_prompt(self, text: str) -> str:
        return (
            "提取简历信息，输出JSON:\n"
            '{"personal_info":{"full_name":"","years_of_experience":0,"current_title":"","current_company":"","gender":"","city":""},'
            '"education_list":[{"school":"","degree":"","major":""}],'
            '"experience_list":[{"company":"","title":"","description":""}],'
            '"skill_list":[{"name":""}],'
            '"project_list":[{"name":"","description":""}]}\n\n'
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
            "max_tokens": 8192,
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
        if "name" in raw and "personal_info" not in raw:
            raw = self._adapt_simple_format(raw)
        pi = PersonalInfo(**raw.get("personal_info", {}))
        edus = [EducationEntry(**e) if isinstance(e, dict) else EducationEntry(school=str(e))
                for e in raw.get("education_list", [])]
        exps = [ExperienceEntry(**e) if isinstance(e, dict) else ExperienceEntry(description=str(e))
                for e in raw.get("experience_list", [])]
        projs = [ProjectEntry(**p) if isinstance(p, dict) else ProjectEntry(name=str(p))
                 for p in raw.get("project_list", [])]
        skill_data = raw.get("skill_list", [])
        skills = []
        for s in skill_data:
            if isinstance(s, dict):
                skills.append(SkillEntry(name=s.get("name", str(s))))
            elif isinstance(s, str):
                skills.append(SkillEntry(name=s))
        return ResumeStructured(
            personal_info=pi, education_list=edus, experience_list=exps,
            project_list=projs, skill_list=skills,
            confidence_score=raw.get("confidence_score", 0.8),
        )

    @staticmethod
    def _adapt_simple_format(raw: Dict[str, Any]) -> Dict[str, Any]:
        pi = {"full_name": raw.get("name", "")}
        edus = [{"school": e, "degree": "", "major": ""} for e in raw.get("education", [])]
        exps = [{"description": e, "company": "", "title": "", "start_date": "", "end_date": ""} for e in raw.get("experience", [])]
        skills = [{"name": s} for s in raw.get("skills", [])]
        return {"personal_info": pi, "education_list": edus, "experience_list": exps, "skill_list": skills, "project_list": [], "confidence_score": 0.7}

    def _fallback(self, msg: str) -> ResumeStructured:
        return ResumeStructured(
            personal_info=PersonalInfo(),
            extraction_warnings=[ExtractionWarning(field="all", message=f"fallback: {msg}", confidence=0.0)],
            confidence_score=0.0,
        )


llm_extractor = LLMExtractor()


def get_llm_extractor() -> LLMExtractor:
    return llm_extractor
