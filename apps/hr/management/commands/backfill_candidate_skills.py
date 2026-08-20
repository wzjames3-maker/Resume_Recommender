# coding=utf-8
"""
    @project: MaxKB
    @file： backfill_candidate_skills.py
    @date：2026/8/16
    @desc：已废止（0030 CandidateSkill 已 DROP）。保留命令桩，避免历史脚本调用报错。
          用法：<env> .venv/bin/python apps/manage.py backfill_candidate_skills [--workspace ws_id]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "已废止：CandidateSkill 已于 0030 DROP，无需回填（桩命令）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default=None, help="仅处理指定工作区（缺省全部）")

    def handle(self, *args, **options):
        self.stdout.write("CandidateSkill 已于 0030 DROP，无需回填。")
