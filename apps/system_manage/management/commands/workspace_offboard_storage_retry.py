# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboard_storage_retry.py
    @date：2026/8/18
    @desc：重试 Workspace 注销后失败的对象存储清理。
          用法：python apps/manage.py workspace_offboard_storage_retry <workspace_id>
"""
from django.core.management.base import BaseCommand, CommandError

from common.exception.app_exception import AppApiException
from system_manage.services.workspace_offboarding import WorkspaceOffboardingService


class Command(BaseCommand):
    help = "重试 Workspace 注销后的失败对象存储清理"

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="已注销的 Workspace ID")

    def handle(self, *args, **options):
        workspace_id = options["workspace_id"]
        try:
            status = WorkspaceOffboardingService.retry_storage_cleanup(workspace_id)
        except AppApiException as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"workspace {workspace_id} storage_status={status['storage_status']} "
            f"attempts={status['storage_cleanup_attempts']} "
            f"pending={len(status['storage_cleanup_errors'])}"
        )
        if status["storage_cleanup_errors"]:
            for item in status["storage_cleanup_errors"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"pending key={item['key']} attempts={item['attempts']} "
                        f"last_error={item['error']} last_error_at={item['last_error_at']}"
                    )
                )
        else:
            self.stdout.write(self.style.SUCCESS("对象存储清理已完成"))
