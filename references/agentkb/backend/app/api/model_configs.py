from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ModelConfig, User, WorkspaceMember
from app.services.crypto import encrypt_secret, mask_key
from app.services.outbound_gateway import validate_endpoint

router = APIRouter(prefix="/api/v1/workspaces", tags=["model_configs"])

class ModelConfigCreate(BaseModel):
    model_type: Literal["llm", "embedding", "rerank"]
    base_url: str
    model_name: str
    api_key: str = Field(..., min_length=1)

class ModelConfigOut(BaseModel):
    id: int
    model_type: str
    base_url: str
    model_name: str
    key_prefix: str
    model_config_revision: int

async def _as_admin(ws_id: int, user_id: int, db: AsyncSession) -> None:
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    m = row.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "资源不存在")
    if m.role not in ("admin", "owner"):
        raise HTTPException(403, "需要 admin 及以上")

@router.post("/{ws_id}/model-configs", status_code=201)
async def upsert_config(ws_id: int, body: ModelConfigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _as_admin(ws_id, user.id, db)
    await validate_endpoint(body.base_url)
    existing = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id, ModelConfig.model_type == body.model_type))
    cfg = existing.scalar_one_or_none()
    if cfg is None:
        cfg = ModelConfig(workspace_id=ws_id, model_type=body.model_type, base_url=body.base_url, model_name=body.model_name, api_key_enc=encrypt_secret(body.api_key), key_prefix=mask_key(body.api_key), model_config_revision=1)
        db.add(cfg)
    else:
        cfg.base_url = body.base_url
        cfg.model_name = body.model_name
        cfg.api_key_enc = encrypt_secret(body.api_key)
        cfg.key_prefix = mask_key(body.api_key)
        cfg.model_config_revision += 1
    await db.commit()
    await db.refresh(cfg)
    return ModelConfigOut(id=cfg.id, model_type=cfg.model_type, base_url=cfg.base_url, model_name=cfg.model_name, key_prefix=cfg.key_prefix, model_config_revision=cfg.model_config_revision)

@router.post("/{ws_id}/model-configs/{model_type}/test", status_code=200)
async def test_config(ws_id: int, model_type: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _as_admin(ws_id, user.id, db)
    row = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id, ModelConfig.model_type == model_type))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(404, "模型配置不存在")
    await validate_endpoint(cfg.base_url)
    # 连接测试：按 PRD F2 校验 LLM structured output / Embedding 维度与距离度量 / Rerank 请求协议与分数方向；
    # 响应大小、超时、并发、重试均受网关限制；API Key 不进入日志；M1 阶段返回占位通过，真实探测在 F2 集成时替换。
    return {"status": "ok", "model_config_revision": cfg.model_config_revision}

@router.get("/{ws_id}/model-configs")
async def list_configs(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "资源不存在")
    rows = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id))
    return {"items": [ModelConfigOut(id=c.id, model_type=c.model_type, base_url=c.base_url, model_name=c.model_name, key_prefix=c.key_prefix, model_config_revision=c.model_config_revision) for c in rows.scalars().all()]}