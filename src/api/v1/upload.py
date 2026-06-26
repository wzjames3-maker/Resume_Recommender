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

    # 11. Indexing: segment -> chunk -> vector write
    try:
        from src.services.indexing import index_resume
        chunk_count = index_resume(resume.id, extracted_doc.raw_text)
        logger.info(f"Vector index write OK: resume_id={resume.id}, chunks={chunk_count}")
    except Exception as e:
        logger.error(f"Vector index write FAILED (non-blocking): resume_id={resume.id}, error={e}")

    return UploadResponse(
        success=True,
        resume_id=resume.id,
        message="简历上传成功",
        parse_status=fallback_result.parse_status.value,
    )
