"""
智能招聘 RAG 推荐系统 - 简历存储服务

提供简历的 CRUD 操作
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

from pymongo.collection import Collection

from src.common.errors import ErrorCode, ResourceNotFoundError, ValidationError
from src.common.logger import get_logger
from src.resume_store.connection import get_resume_collection
from src.resume_store.encryption import get_encryptor
from src.resume_store.models import (
    ResumeCreateRequest,
    ResumeListResponse,
    ResumeResponse,
    ResumeSchema,
    ResumeStatus,
    ResumeUpdateRequest,
)

logger = get_logger("resume_store")


class ResumeStore:
    """简历存储服务"""

    def __init__(self):
        """初始化简历存储服务"""
        self.encryptor = get_encryptor()

    def _get_collection(self) -> Collection:
        """获取简历集合"""
        return get_resume_collection()

    def create(self, user_id: str, request: ResumeCreateRequest) -> ResumeResponse:
        """
        创建简历

        Args:
            user_id: 用户 ID
            request: 创建简历请求

        Returns:
            ResumeResponse: 创建的简历

        Raises:
            ValidationError: 创建失败
        """
        try:
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

            # 加密 PII 字段
            resume_dict = resume.to_mongodb_dict()
            if resume_dict.get("personal_info"):
                resume_dict["personal_info"] = self.encryptor.encrypt_pii_fields(
                    resume_dict["personal_info"]
                )

            # 插入数据库
            collection = self._get_collection()
            result = collection.insert_one(resume_dict)

            if not result.inserted_id:
                raise ValidationError(
                    error_code=ErrorCode.SYS_002,
                    detail="简历创建失败",
                )

            logger.info(f"简历创建成功: {resume.id}, 用户: {user_id}")

            # 返回创建的简历
            return self._resume_to_response(resume)

        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            logger.error(f"简历创建失败: {str(e)}")
            raise ValidationError(
                error_code=ErrorCode.SYS_002,
                detail=f"简历创建失败: {str(e)}",
            )

    def get(self, resume_id: str, user_id: str) -> Optional[ResumeResponse]:
        """
        获取单条简历

        Args:
            resume_id: 简历 ID
            user_id: 用户 ID

        Returns:
            Optional[ResumeResponse]: 简历，如果不存在返回 None
        """
        try:
            collection = self._get_collection()

            # 查询简历（只查询未删除的）
            doc = collection.find_one({
                "id": resume_id,
                "user_id": user_id,
                "status": {"$ne": ResumeStatus.DELETED.value},
            })

            if not doc:
                return None

            # 解密 PII 字段
            if doc.get("personal_info"):
                doc["personal_info"] = self.encryptor.decrypt_pii_fields(
                    doc["personal_info"]
                )

            # 转换为 ResumeSchema
            resume = ResumeSchema.from_mongodb_dict(doc)

            return self._resume_to_response(resume)

        except Exception as e:
            logger.error(f"获取简历失败: {str(e)}")
            return None

    def list(
        self,
        user_id: str,
        status: str = "active",
        page: int = 1,
        size: int = 20,
    ) -> ResumeListResponse:
        """
        获取简历列表

        Args:
            user_id: 用户 ID
            status: 简历状态
            page: 页码（从 1 开始）
            size: 每页数量

        Returns:
            ResumeListResponse: 简历列表
        """
        try:
            collection = self._get_collection()

            # 构建查询条件
            query = {"user_id": user_id}

            # 状态过滤
            if status == "all":
                # 不过滤状态，但排除已删除的
                query["status"] = {"$ne": ResumeStatus.DELETED.value}
            else:
                query["status"] = status

            # 计算总数
            total = collection.count_documents(query)

            # 分页查询
            skip = (page - 1) * size
            cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(size)

            # 转换为响应
            items = []
            for doc in cursor:
                # 解密 PII 字段
                if doc.get("personal_info"):
                    doc["personal_info"] = self.encryptor.decrypt_pii_fields(
                        doc["personal_info"]
                    )

                resume = ResumeSchema.from_mongodb_dict(doc)
                items.append(self._resume_to_response(resume))

            logger.info(f"获取简历列表成功，用户: {user_id}, 总数: {total}")

            return ResumeListResponse(
                items=items,
                total=total,
                page=page,
                size=size,
            )

        except Exception as e:
            logger.error(f"获取简历列表失败: {str(e)}")
            return ResumeListResponse(items=[], total=0, page=page, size=size)

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
            request: 更新简历请求

        Returns:
            bool: 是否更新成功

        Raises:
            ResourceNotFoundError: 简历不存在
        """
        try:
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
                update_data["personal_info"] = self.encryptor.encrypt_pii_fields(
                    request.personal_info.model_dump()
                )

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

        except Exception as e:
            if isinstance(e, ResourceNotFoundError):
                raise
            logger.error(f"简历更新失败: {str(e)}")
            return False

    def soft_delete(self, resume_id: str, user_id: str) -> bool:
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
        try:
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

        except Exception as e:
            if isinstance(e, ResourceNotFoundError):
                raise
            logger.error(f"简历软删除失败: {str(e)}")
            return False

    def _resume_to_response(self, resume: ResumeSchema) -> ResumeResponse:
        """
        将 ResumeSchema 转换为 ResumeResponse

        Args:
            resume: 简历 Schema

        Returns:
            ResumeResponse: 简历响应
        """
        return ResumeResponse(
            id=resume.id,
            user_id=resume.user_id,
            personal_info=resume.personal_info,
            education_list=resume.education_list,
            experience_list=resume.experience_list,
            project_list=resume.project_list,
            skill_list=resume.skill_list,
            status=resume.status,
            created_at=resume.created_at,
            updated_at=resume.updated_at,
        )


# 全局简历存储服务实例
resume_store = ResumeStore()


def get_resume_store() -> ResumeStore:
    """获取简历存储服务实例"""
    return resume_store
