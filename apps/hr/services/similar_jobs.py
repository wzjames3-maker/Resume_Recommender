# coding=utf-8
"""
    @project: MaxKB
    @file： similar_jobs.py
    @date：2026/8/17
    @desc: 相似职位工具（PRD-AGENT-RAG §4.2 similar_jobs）：
           SQL 相似（部门/城市/技能重叠）+ HIRED 录用画像聚合（count/平均年限/高频技能）。
           输出不含任何候选人联系方式；职位库 500 量级，Python 计算足够。
"""
from collections import Counter

from common.exception.app_exception import AppApiException
from hr.models import Application, ApplicationStatus, Job
from hr.services.skill_normalize import normalize_skill


def _hired_profile(workspace_id, job):
    applications = Application.objects.filter(
        workspace_id=workspace_id, job=job, status=ApplicationStatus.HIRED
    ).select_related("candidate")
    years = [app.candidate.years_experience for app in applications if app.candidate.years_experience is not None]
    skill_counter = Counter()
    for application in applications:
        for skill in (application.candidate.skills or []):
            norm = normalize_skill(skill)
            if norm:
                skill_counter[norm] += 1
    return (
        len(applications),
        round(sum(years) / len(years), 1) if years else None,
        [skill for skill, _ in skill_counter.most_common(5)],
    )


def similar_jobs(workspace_id, job_id, limit=5):
    """按技能重叠（0.4）+ 部门（0.3）+ 城市（0.3）打分，附 HIRED 录用画像。"""
    job = Job.objects.filter(workspace_id=workspace_id, id=job_id).first()
    if job is None:
        raise AppApiException(404, "Resource not found")
    limit = max(1, min(10, int(limit)))
    job_skills = {normalize_skill(skill) for skill in (job.skill_requirements or [])}
    candidates = []
    for other in Job.objects.filter(workspace_id=workspace_id).exclude(id=job.id):
        other_skills = {normalize_skill(skill) for skill in (other.skill_requirements or [])}
        overlap = sorted(job_skills & other_skills)
        skill_ratio = len(overlap) / len(job_skills) if job_skills else 0.0
        score = (
            0.4 * skill_ratio
            + 0.3 * (1.0 if other.department and other.department == job.department else 0.0)
            + 0.3 * (1.0 if other.city and other.city == job.city else 0.0)
        )
        if score <= 0:
            continue
        candidates.append({"job": other, "overlap": overlap, "score": score})
    candidates.sort(key=lambda item: item["score"], reverse=True)

    rows = []
    for entry in candidates[:limit]:
        other = entry["job"]
        hired_count, hired_avg_years, hired_top_skills = _hired_profile(workspace_id, other)
        rows.append({
            "job_id": str(other.id),
            "name": other.name,
            "department": other.department,
            "city": other.city,
            "level": other.level,
            "skill_overlap": entry["overlap"],
            "similarity": round(entry["score"], 3),
            "hired_count": hired_count,
            "hired_avg_years": hired_avg_years,
            "hired_top_skills": hired_top_skills,
        })
    return rows
