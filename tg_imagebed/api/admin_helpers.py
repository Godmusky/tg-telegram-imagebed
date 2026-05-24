#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员路由共享辅助函数
"""
from typing import Any

from flask import request, jsonify, Response

from ..utils import add_cache_headers
from ..database import get_system_setting


# Admin API Origin 白名单（main.py 启动时通过 _init_allowed_origins 注入）
_ALLOWED_ADMIN_ORIGINS: list[str] = []


def _init_allowed_origins(config_allowed: list[str]) -> None:
    """在启动时注入允许的 Origin 列表（从 config.py ALLOWED_ORIGINS 读取）"""
    global _ALLOWED_ADMIN_ORIGINS
    _ALLOWED_ADMIN_ORIGINS = list(config_allowed)


def _get_cdn_domain() -> str:
    """从数据库获取 CDN 域名"""
    return str(get_system_setting('cloudflare_cdn_domain') or '').strip()


def _admin_json(data: Any, status: int = 200, cache: str = 'no-cache') -> tuple[Response, int]:
    """创建带 CORS 头的管理员 JSON 响应（Origin 白名单校验）"""
    resp = jsonify(data)
    origin = request.headers.get('Origin', '')
    if origin:
        if origin in _ALLOWED_ADMIN_ORIGINS:
            resp.headers['Access-Control-Allow-Origin'] = origin
        elif _ALLOWED_ADMIN_ORIGINS:
            # 非白名单 Origin 回退到第一个允许的源，浏览器会因不匹配而拦截
            resp.headers['Access-Control-Allow-Origin'] = _ALLOWED_ADMIN_ORIGINS[0]
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    return add_cache_headers(resp, cache), status


def _admin_options(methods: str) -> Response:
    """处理管理员 OPTIONS 预检请求（Origin 白名单校验）"""
    response = Response()
    origin = request.headers.get('Origin', '')
    if origin:
        if origin in _ALLOWED_ADMIN_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
        elif _ALLOWED_ADMIN_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = _ALLOWED_ADMIN_ORIGINS[0]
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = methods
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRF-Token'
    return add_cache_headers(response, 'no-cache')
