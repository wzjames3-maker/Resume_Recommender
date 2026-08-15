# coding=utf-8
"""
    @project: MaxKB
    @file： flow_log.py
    @date：2026/8/15
    @desc：简历数据流转日志：记录上传/提取/清洗/切片/建文档/生命周期各节点的流转数据（可追溯、可审计）。
"""
from hr.models import ResumeFlowLog


def log_flow(
    workspace_id,
    node,
    status="SUCCESS",
    detail=None,
    error_message="",
    resume_id=None,
    candidate_id=None,
    document_id=None,
):
    """写入一条流转日志（幂等无异常：日志失败不阻塞业务）。"""
    try:
        ResumeFlowLog.objects.create(
            workspace_id=workspace_id,
            resume_id=resume_id,
            candidate_id=candidate_id,
            document_id=document_id,
            node=node,
            status=status,
            detail=detail or {},
            error_message=error_message or "",
        )
    except Exception:
        # 日志写入失败不得影响主流程
        pass


def list_flow_logs(workspace_id, resume_id=None, limit=200):
    """按简历查询流转日志（时间正序）。"""
    query = ResumeFlowLog.objects.filter(workspace_id=workspace_id)
    if resume_id:
        query = query.filter(resume_id=resume_id)
    return [
        {
            "id": str(log.id),
            "node": log.node,
            "status": log.status,
            "detail": log.detail,
            "error_message": log.error_message,
            "document_id": str(log.document_id) if log.document_id else None,
            "create_time": log.create_time.isoformat(),
        }
        for log in query.order_by("create_time", "id")[:limit]
    ]
