#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局 API 速率限制模块

对公开端点按 IP 实施请求级速率限制，防止 DoS 滥用：
  - 图片访问 /image/<id>:  100 次/分钟/IP（可通过 RATE_LIMIT_IMAGE 环境变量配置）
  - 上传 /api/upload:       10 次/分钟/IP（可通过 RATE_LIMIT_UPLOAD 环境变量配置）
  - 其他 API /api/*:        30 次/分钟/IP（可通过 RATE_LIMIT_API 环境变量配置）

环境变量格式: "requests,seconds"，例如 RATE_LIMIT_IMAGE="200,30" 表示 200 次/30 秒。
不设环境变量时使用上述默认值。无效格式自动回退到默认值并在日志警告。

与 tg_auth.py 中的终端点级限制器互补：本模块作为全局安全网，
tg_auth.py 对验证码/会话等敏感端点实施更严格的单端点限制。

基于 IP 的纯内存实现（无外部依赖），适配 waitress 多线程模型。
"""

from __future__ import annotations

import os
import time
import threading
from collections import defaultdict

from flask import request, jsonify

from .utils import get_client_ip, add_cache_headers
from .config import logger


# ── 环境变量解析 ─────────────────────────────────────────────────

def _parse_rate_limit_env(env_name: str, default_max: int, default_window: int) -> tuple[int, int]:
    """从环境变量解析速率限制参数。格式: "requests,seconds"。

    示例: RATE_LIMIT_IMAGE="200,30" → (200, 30)
    无效值/未设置时回退到硬编码默认值。
    """
    raw = os.environ.get(env_name, '')
    if not raw:
        return default_max, default_window

    parts = raw.split(',')
    if len(parts) != 2:
        logger.warning(
            f"无效的 {env_name} 格式: {raw!r}，期望 \"requests,seconds\"，"
            f"使用默认值 {default_max}/{default_window}s"
        )
        return default_max, default_window

    try:
        max_req = int(parts[0].strip())
        window_sec = int(parts[1].strip())
    except ValueError:
        logger.warning(
            f"无效的 {env_name} 值: {raw!r}，期望两个整数，"
            f"使用默认值 {default_max}/{default_window}s"
        )
        return default_max, default_window

    if max_req < 1 or window_sec < 1:
        logger.warning(
            f"{env_name} 值必须为正整数: {max_req}/{window_sec}，"
            f"使用默认值 {default_max}/{default_window}s"
        )
        return default_max, default_window

    return max_req, window_sec


# ── SimpleRateLimiter ──────────────────────────────────────────────

class SimpleRateLimiter:
    """线程安全的内存令牌桶（滑动窗口）速率限制器。

    追踪每个 key 在时间窗口内的请求时间戳列表。
    超出 MAX_ENTRIES 时 LRU 淘汰最旧 key，防止内存无限增长。
    """

    _MAX_ENTRIES = 50000  # 追踪的最大 IP 数量

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """检查 key 是否在限制内。返回 True 表示允许，False 表示拒绝。"""
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            reqs = self._requests[key]

            # 清理过期记录
            self._requests[key] = [t for t in reqs if t > cutoff]

            if len(self._requests[key]) >= self._max:
                return False

            # LRU 淘汰：超出最大追踪条目时删除最旧 key
            while len(self._requests) > self._MAX_ENTRIES:
                oldest_key = next(iter(self._requests))
                del self._requests[oldest_key]

            self._requests[key].append(now)
            return True

    @property
    def tracked_entries(self) -> int:
        """当前追踪的 key 数量（调试用）。"""
        with self._lock:
            return len(self._requests)


# ── 速率限制器实例 ─────────────────────────────────────────────────

_image_limiter = SimpleRateLimiter(
    *_parse_rate_limit_env('RATE_LIMIT_IMAGE', default_max=100, default_window=60)
)
_upload_limiter = SimpleRateLimiter(
    *_parse_rate_limit_env('RATE_LIMIT_UPLOAD', default_max=10, default_window=60)
)
_api_limiter = SimpleRateLimiter(
    *_parse_rate_limit_env('RATE_LIMIT_API', default_max=30, default_window=60)
)

# 路径 → 限制器映射
_LIMITERS: dict[str, SimpleRateLimiter] = {
    'image': _image_limiter,
    'upload': _upload_limiter,
    'api': _api_limiter,
}

# 不施加速率限制的路径前缀
_EXEMPT_PREFIXES = (
    '/api/health',   # 健康检查（内部轮询使用）
    '/api/bot/status',
)


def _categorize(path: str) -> str | None:
    """将请求路径归类为 image / upload / api / None。

    None 表示不限制（静态文件、SPA 页面、豁免端点等）。
    """
    path = path.rstrip('/')

    # 豁免端点
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None

    # 图片访问
    if path.startswith('/image/'):
        return 'image'

    # 上传端点
    if path in ('/api/upload', '/upload') or path.startswith('/api/upload/'):
        return 'upload'

    # 其他 API
    if path.startswith('/api/'):
        return 'api'

    # 静态文件、SPA 路由 — 不限速
    return None


def check_rate_limit() -> tuple | None:
    """检查当前请求是否触发速率限制。

    返回 (Flask response, status_code) 若被限制，否则 None。
    """
    path = request.path

    # OPTIONS 预检请求不限速（CORS preflight）
    if request.method == 'OPTIONS':
        return None

    category = _categorize(path)
    if category is None:
        return None

    limiter = _LIMITERS.get(category)
    if limiter is None:
        return None

    ip = get_client_ip(request)

    if not limiter.is_allowed(ip):
        logger.warning(
            f"速率限制触发: IP={ip} path={path} category={category}"
        )
        response = jsonify({
            'success': False,
            'error': '请求过于频繁，请稍后再试',
        })
        add_cache_headers(response, 'no-cache')
        response.headers['Retry-After'] = '60'
        return response, 429

    return None
