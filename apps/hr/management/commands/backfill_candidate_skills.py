# coding=utf-8
"""
    @project: MaxKB
    @file： backfill_candidate_skills.py
    @date：2026/8/16
    @desc：从 Candidate.skills JSON 回填 candidate_skill 归一表（幂等，可重复执行）。
          用法：<env> .venv/bin/python apps/manage.py backfill_candidate_skills [--workspace ws_id]
"""
from django.core.management.base import BaseCommand
from django.db.models import QuerySet

from hr.models import Candidate, CandidateSkill
from hr.services.skill_normalize import normalize_skill


class Command(BaseCommand):
    help = "从 Candidate.skills 回填 candidate_skill 归一表（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default=None, help="仅处理指定工作区（缺省全部）")

    def handle(self, *args, **options):
        query_set = QuerySet(Candidate).all()
        if options.get("workspace"):
            query_set = query_set.filter(workspace_id=options["workspace"])
        inserted = 0
        skipped = 0
        for candidate in query_set:
            existing = set(
                QuerySet(CandidateSkill).filter(candidate=candidate).values_list("skill_norm", flat=True)
            )
            for skill_raw in candidate.skills or []:
                skill_norm = normalize_skill(skill_raw)
                if not skill_norm or skill_norm in existing:
                    continue
                CandidateSkill.objects.create(candidate=candidate, skill_norm=skill_norm, skill_raw=skill_raw)
                existing.add(skill_norm)
                inserted += 1
            skipped += 1
        self.stdout.write(self.style.SUCCESS(f"candidates processed: {skipped}, skill rows inserted: {inserted}"))
