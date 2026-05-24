#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的业务配置管理层 — SettingsManager

优先级：数据库 > 环境变量 > 代码默认值

用法:
    from .settings_manager import settings_manager
    token = settings_manager.get('telegram_bot_token')
    proxy = settings_manager.get_proxy_url()
    extensions = settings_manager.get_allowed_extensions()

设计原则:
  - 模块级导入不触发数据库连接（所有 DB 访问都是 lazy import）
  - 单例模式，全局唯一
  - 线程安全（带缓存）
"""

import os
import threading
import time
from typing import Optional


# ===================== 常量 =====================

# 内置图片后缀（不可删除的基础集合，用于魔数校验回退）
BUILTIN_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}

# 默认允许的完整后缀集合
_DEFAULT_ALLOWED_EXTENSIONS = BUILTIN_IMAGE_EXTENSIONS | {'avif', 'tiff', 'tif', 'ico'}

# 环境变量映射：setting key → 候选环境变量名列表（按优先级排序）
_ENV_MAP: dict = {
    'telegram_bot_token': ['BOT_TOKEN', 'TELEGRAM_BOT_TOKEN'],
    'proxy_url': ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'],
}


# ===================== 辅助函数 =====================

def _normalize_proxy_url(proxy: str) -> str:
    """规范化代理 URL，确保包含协议前缀"""
    proxy = (proxy or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        return f"http://{proxy}"
    return proxy


def _get_env_proxy_url() -> str:
    """直接读取环境变量中的代理 URL（不走 DB）"""
    for name in _ENV_MAP.get('proxy_url', []):
        val = os.environ.get(name, '')
        if val:
            return val
    return ""


# ===================== SettingsManager =====================

class SettingsManager:
    """统一配置管理器（单例）"""

    def __init__(self):
        self._cache: dict = {}  # {key: (value, timestamp)}
        self._lock = threading.Lock()
        self._cache_ttl: float = 5.0  # 默认 TTL 5 秒

    # ── 内部方法 ──────────────────────────────

    def _get_from_db(self, key: str) -> Optional[str]:
        """从数据库读取（lazy import 避免循环依赖）"""
        try:
            from .database import get_system_setting
            return get_system_setting(key)
        except Exception:
            return None

    def _get_from_env(self, key: str) -> str:
        """从环境变量读取（按 _ENV_MAP 优先级）"""
        names = _ENV_MAP.get(key, [])
        for name in names:
            val = os.environ.get(name, '')
            if val:
                return val
        return ""

    def _get_default(self, key: str) -> Optional[str]:
        """从默认值表读取（lazy import 避免循环依赖）"""
        try:
            from .database.settings import DEFAULT_SYSTEM_SETTINGS
            return DEFAULT_SYSTEM_SETTINGS.get(key)
        except Exception:
            return None

    # ── 公开方法 ──────────────────────────────

    def get(self, key: str, ttl: float = 5.0) -> Optional[str]:
        """
        获取设置值，优先级: DB > 环境变量 > 代码默认值

        Args:
            key: 设置键名
            ttl: 缓存有效期(秒)，默认5秒，传0强制刷新

        Returns:
            设置值字符串，或 None
        """
        # 1) 缓存命中（在 TTL 内）
        now = time.time()
        with self._lock:
            if ttl > 0 and key in self._cache:
                cached_val, cached_ts = self._cache[key]
                if (now - cached_ts) < ttl:
                    return cached_val

        # 2) 数据库
        val = self._get_from_db(key)
        if val is not None and val != '':
            with self._lock:
                self._cache[key] = (val, now)
            return val

        # 3) 环境变量
        val = self._get_from_env(key)
        if val:
            with self._lock:
                self._cache[key] = (val, now)
            return val

        # 4) 代码默认值
        val = self._get_default(key)
        with self._lock:
            self._cache[key] = (val, now)
        return val

    def get_int(self, key: str, default: int = 0,
                minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
        """获取 int 类型设置（带容错/范围约束）"""
        try:
            val = int(self.get(key) or default)
        except (TypeError, ValueError):
            val = default
        if minimum is not None:
            val = max(minimum, val)
        if maximum is not None:
            val = min(maximum, val)
        return val

    def invalidate(self, key: Optional[str] = None) -> None:
        """使缓存失效。key=None 时清空全部缓存"""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def get_proxy_url(self) -> str:
        """
        获取代理 URL（优先 DB，回退环境变量）

        与 config.py 中原 get_proxy_url() 行为完全一致。
        通过 self.get() 复用 TTL 缓存，避免高频穿透 DB。
        """
        db_proxy = (self.get('proxy_url') or '').strip()
        if db_proxy:
            return _normalize_proxy_url(db_proxy)
        return _normalize_proxy_url(_get_env_proxy_url())

    def has_env_proxy(self) -> bool:
        """检查是否有环境变量级别的代理设置"""
        return bool(_get_env_proxy_url())

    def get_allowed_extensions(self) -> set:
        """
        获取允许的文件后缀集合（从数据库读取，回退内置默认值）

        与 config.py 中原 get_allowed_extensions() 行为完全一致。
        通过 self.get() 复用 TTL 缓存，避免高频穿透 DB。
        """
        raw = (self.get('allowed_extensions') or '').strip()
        if raw:
            exts = {e.strip().lower().lstrip('.') for e in raw.split(',') if e.strip()}
            return exts | BUILTIN_IMAGE_EXTENSIONS  # 始终包含内置后缀
        return set(_DEFAULT_ALLOWED_EXTENSIONS)


# 模块级单例
settings_manager = SettingsManager()
