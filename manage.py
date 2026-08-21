#!/usr/bin/env python
"""Django's command-line utility for administrative tasks - 标准入口 (项目根)."""
import os
import sys


def main():
    """Run administrative tasks."""
    # 兼容 src 布局：apps/ 下的业务 App 需要加入 sys.path
    # 标准 Django 要求 manage.py 在项目根，maxkb 包也在根，apps 为可选子目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APPS_DIR = os.path.join(BASE_DIR, "apps")
    if APPS_DIR not in sys.path:
        sys.path.insert(0, APPS_DIR)
    # 同时确保项目根在 sys.path（正常已在，但显式保证）
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maxkb.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
