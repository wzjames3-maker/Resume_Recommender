# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboard.py
    @date：2026/8/18
    @desc：内核 Workspace 跨域注销编排命令。
          先 dry-run/export，再显式 --force 清理非空工作区；默认保留 WorkspaceOffboard tombstone。
          用法：python apps/manage.py workspace_offboard <workspace_id> [--dry-run] [--force]
                [--export <dir>] [--user-id <uuid>]
"""
import uuid_utils.compat as uuid
from django.core.management.base import BaseCommand

from system_manage.services.workspace_offboarding import WorkspaceOffboardingService


class Command(BaseCommand):
    help = "Workspace 跨内核域注销（application/knowledge/model/permission/chat/HR）"

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="目标工作区 ID")
        parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
        parser.add_argument("--force", action="store_true", help="确认清理非空/活跃工作区")
        parser.add_argument("--export", type=str, default=None, help="数据返还 JSON 输出目录")
        parser.add_argument("--user-id", type=str, default=None, help="执行人 UUID，缺省系统执行人")

    def handle(self, *args, **options):
        raw_user_id = options.get("user_id")
        try:
            user_id = uuid.UUID(str(raw_user_id)) if raw_user_id else None
        except (ValueError, TypeError) as exc:
            raise SystemExit("--user-id 不是合法 UUID") from exc
        result = WorkspaceOffboardingService.offboard(
            options["workspace_id"],
            user_id=user_id,
            force=options["force"],
            dry_run=options["dry_run"],
            export_dir=options.get("export"),
        )
        status = result["status"]
        if status == "ALREADY_OFFBOARDED":
            self.stdout.write(self.style.WARNING(
                f"workspace {result['workspace_id']} 已注销（{result['offboarded_at']}），无需重复执行"
            ))
            return
        self.stdout.write(f"workspace {result['workspace_id']} counts: {result['counts']}")
        if status == "DRY_RUN":
            self.stdout.write(self.style.NOTICE("dry-run 完成：未做任何删除"))
            return
        if status == "BLOCKED":
            self.stdout.write(self.style.ERROR(
                "工作区存在不可忽略数据/活跃业务，拒绝注销（确认清理请加 --force）：\n  - "
                + "\n  - ".join(result.get("active_issues") or [])
            ))
            return
        if result.get("exported_path"):
            self.stdout.write(f"exported: {result['exported_path']}")
        self.stdout.write(self.style.SUCCESS(
            f"workspace {result['workspace_id']} 已注销；存储回收错误={len(result.get('storage_cleanup_errors') or [])}"
        ))
