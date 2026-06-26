"""
智能招聘 RAG 推荐系统 - Resume 数据仓库层

Repository 模式隔离数据访问层
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import DESCENDING
from pymongo.collection import Collection

from src.common.errors import ErrorCode, ResourceNotFoundError, ValidationError
from src.common.logger import get_logger
from src.resume_parser.pii_handler import get_pii_handler
from src.resume_store.connection import get_resume_collection
from src.resume_store.models import (
    ResumeCreateRequest,
    ResumeListResponse,
    ResumeResponse,
    ResumeSchema,
    ResumeStatus,
    ResumeUpdateRequest,
)

logger = get_logger("resume_repository")


class ResumeRepository:
    """Resume 数据仓库"""

    def __init__(self):
        """初始化数据仓库"""
        self.pii_handler = get_pii_handler()

    def _get_collection(self) -> Collection:
        """获取 MongoDB Collection"""
        return get_resume_collection()

    def create(
        self,
        user_id: str,
        request: ResumeCreateRequest,
        file_md5: Optional[str] = None,
    ) -> ResumeResponse:
        """
        创建简历

        Args:
            user_id: 用户 ID
            request: 创建请求
            file_md5: 文件 MD5（用于去重）

        Returns:
            ResumeResponse: 创建的简历

        Raises:
            ValidationError: 创建失败或文件已存在
        """
        # 检查 MD5 去重
        if file_md5:
            existing = self.find_by_md5(file_md5)
            if existing:
                raise ValidationError(
                    error_code=ErrorCode.RESUME_006,
                    detail=f"文件已存在，简历 ID: {existing.id}",
                )

        # 创建简历 Schema
        resume = ResumeSchema(
            user_id=user_id,
            personal_info=request.personal_info,
            education_list=request.education_list,
            experience_list=request.experience_list,
            project_list=request.project_list,
            skill_list=request.skill_list,
            raw_text=request.raw_text,
        )

        # 准备数据库文档
        doc = resume.to_mongodb_dict()
        doc["file_md5"] = file_md5

        # 加密 PII 字段
        encrypted_fields = []
        if doc.get("personal_info"):
            if doc["personal_info"].get("phone"):
                doc["personal_info"]["phone"] = self.pii_handler.encryptor.encrypt(
                    doc["personal_info"]["phone"]
                )
                encrypted_fields.append("personal_info.phone")
            if doc["personal_info"].get("email"):
                doc["personal_info"]["email"] = self.pii_handler.encryptor.encrypt(
                    doc["personal_info"]["email"]
                )
                encrypted_fields.append("personal_info.email")

        doc["_encrypted_fields"] = encrypted_fields

        # 插入数据库
        collection = self._get_collection()
        result = collection.insert_one(doc)

        if not result.inserted_id:
            raise ValidationError(
                error_code=ErrorCode.SYS_002,
                detail="简历创建失败",
            )

        logger.info(f"简历创建成功: {resume.id}, 用户: {user_id}")

        return self._to_response(resume)

    def get(
        self,
        resume_id: str,
        user_id: Optional[str] = None,
        decrypt_pii: bool = False,
    ) -> ResumeResponse:
        """
        获取简历

        Args:
            resume_id: 简历 ID
            user_id: 用户 ID（可选，用于权限检查）
            decrypt_pii: 是否解密 PII 字段

        Returns:
            ResumeResponse: 简历数据

        Raises:
            ResourceNotFoundError: 简历不存在
        """
        collection = self._get_collection()

        # 构建查询条件
        query = {
            "id": resume_id,
            "status": {"$ne": ResumeStatus.DELETED.value},
        }

        if user_id:
            query["user_id"] = user_id

        doc = collection.find_one(query)

        if not doc:
            raise ResourceNotFoundError(
                error_code=ErrorCode.RESUME_001,
                detail=f"简历不存在: {resume_id}",
            )

        # 解密 PII 字段
        if decrypt_pii:
            encrypted_fields = doc.get("_encrypted_fields", [])
            if encrypted_fields:
                doc = self.pii_handler.decrypt_pii_fields(
                    doc,
                    encrypted_fields,
                    user_id=user_id,
                    resume_id=resume_id,
                )

        resume = ResumeSchema.from_mongodb_dict(doc)
        return self._to_response(resume)

    def find_by_md5(self, file_md5: str) -> Optional[ResumeResponse]:
        """
        通过 MD5 查找简历

        Args:
            file_md5: 文件 MD5

        Returns:
            Optional[ResumeResponse]: 简历数据，不存在返回 None
        """
        collection = self._get_collection()

        doc = collection.find_one({
            "file_md5": file_md5,
            "status": ResumeStatus.ACTIVE.value,
        })

        if not doc:
            return None

        resume = ResumeSchema.from_mongodb_dict(doc)
        return self._to_response(resume)

    def list(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
        status: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> ResumeListResponse:
        """
        列表查询简历（返回脱敏数据）

        Args:
            user_id: 用户 ID
            page: 页码（从 1 开始）
            size: 每页数量
            status: 状态筛选
            sort_by: 排序字段
            sort_order: 排序方向（asc/desc）

        Returns:
            ResumeListResponse: 简历列表（脱敏数据）
        """
        collection = self._get_collection()

        # 构建查询条件
        query = {"user_id": user_id}

        if status:
            query["status"] = status
        else:
            query["status"] = {"$ne": ResumeStatus.DELETED.value}

        # 计算总数
        total = collection.count_documents(query)

        # 分页查询
        skip = (page - 1) * size
        sort_direction = DESCENDING if sort_order == "desc" else 1

        cursor = (
            collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(skip)
            .limit(size)
        )

        # 转换为响应（脱敏数据）
        items = []
        for doc in cursor:
            resume = ResumeSchema.from_mongodb_dict(doc)
            items.append(self._to_response(resume, desensitize=True))

        logger.info(f"列表查询成功，用户: {user_id}, 总数: {total}")

        return ResumeListResponse(
            items=items,
            total=total,
            page=page,
            size=size,
        )

    def update(
        self,
        resume_id: str,
        user_id: str,
        request: ResumeUpdateRequest,
    ) -> bool:
        """
        更新简历

        Args:
            resume_id: 简历 ID
            user_id: 用户 ID
            request: 更新请求

        Returns:
            bool: 是否更新成功

        Raises:
            ResourceNotFoundError: 简历不存在
        """
        collection = self._get_collection()

        # 检查简历是否存在
        existing = collection.find_one({
            "id": resume_id,
            "user_id": user_id,
            "status": {"$ne": ResumeStatus.DELETED.value},
        })

        if not existing:
            raise ResourceNotFoundError(
                error_code=ErrorCode.RESUME_001,
                detail=f"简历不存在: {resume_id}",
            )

        # 构建更新数据
        update_data = {}
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        if request.personal_info is not None:
            update_data["personal_info"] = request.personal_info.model_dump()

        if request.education_list is not None:
            update_data["education_list"] = [
                item.model_dump() for item in request.education_list
            ]

        if request.experience_list is not None:
            update_data["experience_list"] = [
                item.model_dump() for item in request.experience_list
            ]

        if request.project_list is not None:
            update_data["project_list"] = [
                item.model_dump() for item in request.project_list
            ]

        if request.skill_list is not None:
            update_data["skill_list"] = [
                item.model_dump() for item in request.skill_list
            ]

        if request.status is not None:
            update_data["status"] = request.status.value

        # 执行更新
        result = collection.update_one(
            {"id": resume_id, "user_id": user_id},
            {"$set": update_data},
        )

        if result.modified_count == 0:
            logger.warning(f"简历未发生变化: {resume_id}")
            return True

        logger.info(f"简历更新成功: {resume_id}, 用户: {user_id}")

        return True

    def delete(self, resume_id: str, user_id: str) -> bool:
        """
        软删除简历

        Args:
            resume_id: 简历 ID
            user_id: 用户 ID

        Returns:
            bool: 是否删除成功

        Raises:
            ResourceNotFoundError: 简历不存在
        """
        collection = self._get_collection()

        # 检查简历是否存在
        existing = collection.find_one({
            "id": resume_id,
            "user_id": user_id,
            "status": {"$ne": ResumeStatus.DELETED.value},
        })

        if not existing:
            raise ResourceNotFoundError(
                error_code=ErrorCode.RESUME_001,
                detail=f"简历不存在: {resume_id}",
            )

        # 执行软删除
        result = collection.update_one(
            {"id": resume_id, "user_id": user_id},
            {
                "$set": {
                    "status": ResumeStatus.DELETED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )

        if result.modified_count == 0:
            logger.warning(f"简历软删除失败: {resume_id}")
            return False

        logger.info(f"简历软删除成功: {resume_id}, 用户: {user_id}")

        return True

    def batch_create(
        self,
        user_id: str,
        requests: List[Tuple[ResumeCreateRequest, Optional[str]]],
    ) -> List[ResumeResponse]:
        """
        批量创建简历

        Args:
            user_id: 用户 ID
            requests: [(创建请求, file_md5), ...]

        Returns:
            List[ResumeResponse]: 创建的简历列表
        """
        results = []

        for request, file_md5 in requests:
            try:
                resume = self.create(user_id, request, file_md5)
                results.append(resume)
            except Exception as e:
                logger.error(f"批量创建失败: {str(e)}")
                # 跳过失败的简历，继续处理其他简历
                continue

        logger.info(f"批量创建完成: {len(results)}/{len(requests)}")

        return results

    def batch_delete(
        self, resume_ids: List[str], user_id: str
    ) -> int:
        """
        批量软删除简历

        Args:
            resume_ids: 简历 ID 列表
            user_id: 用户 ID

        Returns:
            int: 成功删除的数量
        """
        success_count = 0

        for resume_id in resume_ids:
            try:
                if self.delete(resume_id, user_id):
                    success_count += 1
            except Exception as e:
                logger.error(f"批量删除失败 {resume_id}: {str(e)}")
                continue

        logger.info(f"批量删除完成: {success_count}/{len(resume_ids)}")

        return success_count

    def _to_response(
        self, resume: ResumeSchema, desensitize: bool = False
    ) -> ResumeResponse:
        """
        转换为响应

        Args:
            resume: 简历 Schema
            desensitize: 是否脱敏

        Returns:
            ResumeResponse: 响应
        """
        personal_info = resume.personal_info

        if desensitize:
            # 脱敏处理
            if personal_info.phone:
                personal_info.phone = self._mask_phone(personal_info.phone)
            if personal_info.email:
                personal_info.email = self._mask_email(personal_info.email)

        return ResumeResponse(
            id=resume.id,
            user_id=resume.user_id,
            personal_info=personal_info,
            education_list=resume.education_list,
            experience_list=resume.experience_list,
            project_list=resume.project_list,
            skill_list=resume.skill_list,
            raw_text=resume.raw_text,
            status=resume.status,
            created_at=resume.created_at,
            updated_at=resume.updated_at,
        )

    def _mask_phone(self, phone: str) -> str:
        """
        手机号脱敏

        Args:
            phone: 手机号

        Returns:
            str: 脱敏后的手机号
        """
        if not phone or len(phone) < 7:
            return phone

        # 保留前3位 + **** + 后4位（如果长度>=11），否则后3位
        suffix_len = 4 if len(phone) >= 11 else 3
        return phone[:3] + "****" + phone[-suffix_len:]

    def _mask_email(self, email: str) -> str:
        """
        邮箱脱敏

        Args:
            email: 邮箱

        Returns:
            str: 脱敏后的邮箱
        """
        if not email or "@" not in email:
            return email

        local, domain = email.split("@", 1)

        # 保留前3字符（如果>=3），否则保留前2字符（如果>=2），否则保留前1字符
        if len(local) >= 3:
            masked_local = local[:3] + "***"
        elif len(local) >= 2:
            masked_local = local[:2] + "***"
        else:
            masked_local = local[0] + "***"

        return f"{masked_local}@{domain}"


# 全局数据仓库实例
resume_repository = ResumeRepository()


def get_resume_repository() -> ResumeRepository:
    """获取数据仓库实例"""
    return resume_repository
