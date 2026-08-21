# -*- coding: utf-8 -*-
#
import os
from pathlib import Path

from dotenv import load_dotenv

from .conf import ConfigManager

__all__ = ['BASE_DIR', 'PROJECT_DIR', 'VERSION', 'CONFIG']

# 标准布局：maxkb 位于项目根，PROJECT_DIR 为项目根 (tob)，BASE_DIR 为 apps 目录以兼容旧路径
# 使用 resolve() 处理 symlink (apps/maxkb -> ../maxkb) 场景，确保无论通过 maxkb 还是 apps.maxkb 导入都能得到正确路径
PROJECT_DIR = str(Path(__file__).resolve().parent.parent)
BASE_DIR = os.path.join(PROJECT_DIR, 'apps')
LOG_DIR = os.getenv('MAXKB_LOG_DIR') or os.path.join(PROJECT_DIR, 'logs')
VERSION = '2.0.0'

# load environment variables from .env file
load_dotenv()
# print(os.getenv('MAXKB_CONFIG'))
if os.getenv('MAXKB_CONFIG') is not None:
    CONFIG = ConfigManager.load_user_config(root_path=PROJECT_DIR)
else:
    CONFIG = ConfigManager.load_user_config(root_path=os.path.abspath('/opt/maxkb/conf'))

