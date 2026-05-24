#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块 — 纯基础设施配置

所有业务配置（Bot Token、CDN、存储等）通过 management 后台（数据库）管理。
业务配置的访问层统一在 settings_manager.py（DB > 环境变量 > 代码默认值）。
此文件仅保留路径、服务器参数、日志等基础设施常量。
"""
import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _normalize_proxy_url(proxy: str) -> str:
    """规范化代理 URL，确保包含协议前缀"""
    proxy = (proxy or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        return f"http://{proxy}"
    return proxy


# ===================== 基础路径配置 =====================
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = str(BASE_DIR / "frontend")
STATIC_FOLDER = str(BASE_DIR / "frontend" / ".output" / "public")

# 数据目录（固定，Docker 通过 volume 映射 ./data:/app/data）
DATA_DIR = str(BASE_DIR / "data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(DATA_DIR, "telegram_imagebed.db")
LOG_FILE = os.path.join(DATA_DIR, "telegram_imagebed.log")

# ===================== 服务器配置（硬编码） =====================
PORT = 18793
HOST = '0.0.0.0'
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').strip() or '*'
SESSION_LIFETIME = 3600
REMEMBER_ME_LIFETIME = 30 * 24 * 3600

# ===================== 版本 & 启动时间 =====================
STATIC_VERSION = str(int(time.time()))
START_TIME = time.time()

# ===================== 代理（标准系统环境变量，非 .env） =====================
_http_proxy = os.environ.get("HTTP_PROXY", "") or os.environ.get("http_proxy", "")
_https_proxy = os.environ.get("HTTPS_PROXY", "") or os.environ.get("https_proxy", "")
PROXY_URL = _normalize_proxy_url(_http_proxy or _https_proxy)


# ===================== SECRET_KEY — 持久化到文件 =====================
_secret_key_file = os.path.join(DATA_DIR, '.secret_key')
try:
    if os.path.exists(_secret_key_file):
        with open(_secret_key_file, 'r', encoding='utf-8') as f:
            _secret_key = f.read().strip()
    else:
        _secret_key = ""
except Exception:
    _secret_key = ""

if not _secret_key:
    import secrets as _secrets
    _secret_key = _secrets.token_hex(32)
    try:
        with open(_secret_key_file, 'w', encoding='utf-8') as f:
            f.write(_secret_key)
        os.chmod(_secret_key_file, 0o600)
    except Exception:
        pass
else:
    try:
        os.chmod(_secret_key_file, 0o600)
    except Exception:
        pass

SECRET_KEY = _secret_key

# ===================== 日志配置 =====================
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL),
    handlers=[
        RotatingFileHandler(
            LOG_FILE, encoding='utf-8',
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('waitress').setLevel(logging.WARNING)
logging.getLogger('waitress.queue').setLevel(logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# ===================== 登录安全配置 =====================
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_DURATIONS = [300, 900, 1800]
LOGIN_ATTEMPT_WINDOW = 900
MAX_CONCURRENT_SESSIONS = 3

# ===================== 单实例锁文件 =====================
if sys.platform == 'win32':
    LOCK_FILE = os.path.join(os.environ.get('TEMP', '.'), 'telegram_imagebed.lock')
else:
    LOCK_FILE = '/tmp/telegram_imagebed.lock'


__all__ = [
    # 基础路径
    'BASE_DIR', 'FRONTEND_DIR', 'STATIC_FOLDER', 'DATA_DIR',
    # 数据库 & 日志
    'DATABASE_PATH', 'LOG_FILE', 'LOG_LEVEL', 'logger',
    # 服务器
    'PORT', 'HOST', 'ALLOWED_ORIGINS', 'SESSION_LIFETIME', 'REMEMBER_ME_LIFETIME',
    # 版本 & 时间
    'STATIC_VERSION', 'START_TIME',
    # 安全
    'SECRET_KEY',
    # 登录安全
    'LOGIN_MAX_ATTEMPTS', 'LOGIN_LOCKOUT_DURATIONS', 'LOGIN_ATTEMPT_WINDOW',
    'MAX_CONCURRENT_SESSIONS',
    # 代理（基础常量，仅环境变量级别）
    'PROXY_URL',
    # 锁文件
    'LOCK_FILE',
]
