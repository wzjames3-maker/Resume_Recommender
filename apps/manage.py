#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks. 兼容旧路径：apps/manage.py -> 转发到项目根 manage.py"""
    # 兼容标准布局：项目根的 maxkb 需要在 sys.path
    _current = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_current)  # apps/ -> tob/
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    if _current not in sys.path:
        sys.path.insert(0, _current)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
