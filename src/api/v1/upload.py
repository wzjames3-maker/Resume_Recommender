"""
智能招聘 RAG 推荐系统 - 简历上传 API 路由

/api/v1/resumes/upload 端点
"""

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from src.common.errors import ErrorCode, ValidationError
from src.common.logger import get_logger
from src.common.middleware.rbac import require_permission
from src.resume_parser.fallback_handler import get_fallback_handler
from src.resume_parser.llm_extractor import get_llm_extractor
from src.resume_parser.text_extractor import get_text_extractor
from src.resume_store.repository import get_resume_repository

logger = get_logger("api_upload")

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])

MAX_SIZE = 10 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".docx", ".json"}
ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json",
}


class UploadResponse(BaseModel):
    """上传响应"""
    success: bool = Field(..., description="是否成功")
    resume_id: Optional[str] = Field(None, description="简历 ID")
    message: str = Field(..., description="消息")
    parse_status: Optional[str] = Field(None, description="解析状态")
    index_status: Optional[str] = Field(None, description="索引状态: indexed | failed")


@router.post("/upload", response_model=UploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permission("resume:create")),
):
    """上传简历（支持 PDF、DOCX、JSON 格式，≤10MB）"""
    user_id = current_user.get("sub", "default")
    logger.info(f"收到简历上传请求: user_id={user_id}, filename={file.filename}")

    # 1. 校验扩展名
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValidationError(error_code=ErrorCode.RESUME_003, detail=f"不支持的格式: {ext}")

    # 2. 读取文件内容
    content = await file.read()

    # 3. 校验文件大小
    if len(content) > MAX_SIZE:
        raise ValidationError(error_code=ErrorCode.RESUME_004, detail="文件超过 10MB")

    # 4. 校验 MIME 类型
    if file.content_type and file.content_type not in ALLOWED_MIME:
        raise ValidationError(error_code=ErrorCode.RESUME_003, detail=f"MIME 类型不允许: {file.content_type}")

    # 5. 计算文件 MD5
    file_md5 = hashlib.md5(content).hexdigest()

    # 6. 检查是否已存在
    repository = get_resume_repository()
    existing = repository.find_by_md5(file_md5)
    if existing:
        return UploadResponse(
            success=True,
            resume_id=existing.id,
            message="文件已存在",
            parse_status="skipped",
        )

    # 7. 提取文本
    text_extractor = get_text_extractor()
    extracted_doc = text_extractor.extract(content, file.filename)

    # 8. LLM 结构化提取
    llm_extractor = get_llm_extractor()
    structured = llm_extractor.extract(extracted_doc.raw_text)

    # 9. 降级处理
    fallback_handler = get_fallback_handler()
    fallback_result = fallback_handler.handle(extracted_doc.raw_text, structured)

    # 10. 存储简历
    from src.resume_store.models import ResumeCreateRequest
    effective = fallback_result.structured if fallback_result.structured else structured
    request = ResumeCreateRequest(
        personal_info=effective.personal_info if effective else None,
        education_list=effective.education_list if effective else [],
        experience_list=effective.experience_list if effective else [],
        skill_list=effective.skill_list if effective else [],
        project_list=effective.project_list if effective else [],
        raw_text=extracted_doc.raw_text,
    )
    resume = repository.create(user_id, request, file_md5)
    logger.info(f"简历上传成功: resume_id={resume.id}")

    # 11. Indexing: segment -> chunk -> vector write (带重试机制)
    index_status = "indexed"
    max_retries = 2
    for attempt in range(max_retries):
        try:
            from src.services.indexing import index_resume
            chunk_count = index_resume(resume.id, extracted_doc.raw_text)
            logger.info(f"Vector index write OK: resume_id={resume.id}, chunks={chunk_count}")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Vector index write attempt {attempt+1} FAILED, retrying: {e}")
                import time
                time.sleep(1)  # 重试前等待 1 秒
            else:
                logger.error(f"Vector index write FAILED after {max_retries} attempts: resume_id={resume.id}, error={e}")
                index_status = "failed"
                # 标记简历需要重建索引
                try:
                    collection = repository._get_collection()
                    collection.update_one(
                        {"id": resume.id},
                        {"$set": {"_index_status": "pending", "_index_error": str(e)}}
                    )
                except Exception as mark_err:
                    logger.error(f"Failed to mark resume for reindex: {mark_err}")

    return UploadResponse(
        success=True,
        resume_id=resume.id,
        message="简历上传成功" if index_status == "indexed" else "简历已保存，但索引创建失败，搜索可能不准确",
        parse_status=fallback_result.parse_status.value,
        index_status=index_status,
    )


# ============================================================
# 简历 CRUD + 统计 API（供前端调用，替代直连 MongoDB）
# ============================================================

from typing import List, Optional
from src.resume_store.models import ResumeUpdateRequest


@router.get("/")
async def list_resumes(
    keyword: Optional[str] = None,
    skill: Optional[str] = None,
    city: Optional[str] = None,
    education: Optional[str] = None,
    min_exp: int = 0,
    is_985: bool = False,
    is_211: bool = False,
    page: int = 1,
    size: int = 20,
    current_user: dict = Depends(require_permission("resume:read")),
):
    """获取简历列表（支持关键词/技能/城市/学历/经验/院校筛选）"""
    user_id = current_user.get("sub", "default")
    repository = get_resume_repository()

    # 使用 repository 的 list
    result = repository.list(
        user_id=user_id,
        page=page,
        size=size,
    )

    items = [item.model_dump(mode="json") for item in result.items]

    # 内存过滤（keyword/skill/city/education/min_exp/is_985/is_211）
    if keyword:
        kw = keyword.lower()
        items = [
            r for r in items
            if kw in (r.get("personal_info", {}).get("full_name", "") or "").lower()
            or any(kw in (s.get("name", "") or "").lower() for s in r.get("skill_list", []))
        ]
    if skill:
        sk = skill.lower()
        items = [r for r in items if any(sk in (s.get("name", "") or "").lower() for s in r.get("skill_list", []))]
    if city:
        ct = city.lower()
        items = [r for r in items if ct in (r.get("personal_info", {}).get("expected_city", "") or "").lower()]
    if education:
        ed = education.lower()
        items = [r for r in items if ed in (r.get("personal_info", {}).get("highest_education", "") or "").lower()]
    if min_exp and min_exp > 0:
        items = [
            r for r in items
            if (r.get("personal_info", {}).get("years_of_experience") or 0) >= min_exp
        ]
    if is_985:
        items = [r for r in items if any(e.get("is_985") for e in r.get("education_list", []))]
    if is_211:
        items = [r for r in items if any(e.get("is_211") for e in r.get("education_list", []))]

    return {"items": items, "total": len(items), "page": page, "size": size}


@router.get("/stats")
async def get_resume_stats(
    current_user: dict = Depends(require_permission("resume:read")),
):
    """获取简历统计信息"""
    user_id = current_user.get("sub", "default")
    repository = get_resume_repository()

    # 获取所有简历（最多 1000 条用于统计）
    result = repository.list(user_id=user_id, page=1, size=1000)
    resumes = [item.model_dump(mode="json") for item in result.items]

    # 技能统计
    skill_count = {}
    for r in resumes:
        for s in r.get("skill_list", []):
            name = s.get("name", "")
            if name:
                skill_count[name] = skill_count.get(name, 0) + 1
    skills = [{"_id": k, "count": v} for k, v in sorted(skill_count.items(), key=lambda x: x[1], reverse=True)[:50]]

    # 学历统计
    edu_count = {}
    for r in resumes:
        edu = r.get("personal_info", {}).get("highest_education", "")
        if edu:
            edu_count[edu] = edu_count.get(edu, 0) + 1
    educations = [{"_id": k, "count": v} for k, v in sorted(edu_count.items(), key=lambda x: x[1], reverse=True)]

    # 城市统计
    city_count = {}
    for r in resumes:
        c = r.get("personal_info", {}).get("expected_city", "")
        if c:
            city_count[c] = city_count.get(c, 0) + 1
    cities = [{"_id": k, "count": v} for k, v in sorted(city_count.items(), key=lambda x: x[1], reverse=True)[:20]]

    # 公司统计
    company_count = {}
    for r in resumes:
        for exp in r.get("experience_list", []):
            comp = exp.get("company", "")
            if comp:
                company_count[comp] = company_count.get(comp, 0) + 1
    companies = [{"_id": k, "count": v} for k, v in sorted(company_count.items(), key=lambda x: x[1], reverse=True)[:20]]

    return {
        "total_resumes": len(resumes),
        "skills": skills,
        "educations": educations,
        "cities": cities,
        "companies": companies,
    }


@router.get("/{resume_id}")
async def get_resume_detail(
    resume_id: str,
    current_user: dict = Depends(require_permission("resume:read")),
):
    """获取简历详情"""
    user_id = current_user.get("sub", "default")
    repository = get_resume_repository()
    resume = repository.get(resume_id, user_id=user_id, decrypt_pii=True)
    return resume.model_dump(mode="json")


@router.put("/{resume_id}")
async def update_resume(
    resume_id: str,
    request: ResumeUpdateRequest,
    current_user: dict = Depends(require_permission("resume:update")),
):
    """更新简历"""
    user_id = current_user.get("sub", "default")
    repository = get_resume_repository()
    repository.update(resume_id, user_id, request)
    return {"success": True}


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: str,
    current_user: dict = Depends(require_permission("resume:delete")),
):
    """软删除简历"""
    user_id = current_user.get("sub", "default")
    repository = get_resume_repository()
    repository.delete(resume_id, user_id)
    return {"success": True}
