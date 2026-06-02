#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram图床机器人 - 管理员功能模块（简化版）
提供Web管理后台功能
"""
from __future__ import annotations

import os
import sqlite3
import hashlib
import secrets
import logging
import time
import json
import re
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import session, request, jsonify, redirect, url_for
from flask.sessions import SecureCookieSessionInterface

from .database.connection import get_connection

# 日志配置
logger = logging.getLogger(__name__)

# ===================== 画集域名 SSO Token 存储 =====================
# 格式: {token_str: {'created_at': float, 'username': str, 'used': bool}}
_gallery_auth_tokens: dict[str, dict] = {}
# 多线程并发保护锁（waitress 多线程模型下必须加锁）
_gallery_auth_tokens_lock = threading.Lock()

_GALLERY_TOKEN_EXPIRE_SECONDS = 60  # token 有效期 60 秒


def _cleanup_gallery_tokens() -> None:
    """清理过期的画集 SSO token（调用方须持有锁）"""
    now = time.time()
    expired = [
        t for t, info in _gallery_auth_tokens.items()
        if now - info['created_at'] > _GALLERY_TOKEN_EXPIRE_SECONDS
    ]
    for t in expired:
        del _gallery_auth_tokens[t]


def generate_gallery_auth_token(username: str) -> str:
    """生成一次性画集 SSO token（60秒有效，一次性使用）"""
    with _gallery_auth_tokens_lock:
        _cleanup_gallery_tokens()
        token = secrets.token_urlsafe(32)
        _gallery_auth_tokens[token] = {
            'created_at': time.time(),
            'username': username,
            'used': False,
        }
    return token


def verify_gallery_auth_token(token: str) -> tuple[bool, str]:
    """
    验证画集 SSO token
    返回: (valid, username)
    验证后立即标记为已使用，防止重放
    """
    with _gallery_auth_tokens_lock:
        _cleanup_gallery_tokens()
        info = _gallery_auth_tokens.get(token)
        if not info:
            return False, ''
        if info['used']:
            return False, ''
        if time.time() - info['created_at'] > _GALLERY_TOKEN_EXPIRE_SECONDS:
            del _gallery_auth_tokens[token]
            return False, ''
        # 标记为已使用（原子操作，防止重放攻击）
        info['used'] = True
        return True, info['username']


from .utils import get_domain, get_image_domain, format_size, get_client_ip

from .device_fingerprint import (
    parse_user_agent,
    build_device_label,
    normalize_device_name,
)
try:
    from .config import (
        SESSION_LIFETIME,
        REMEMBER_ME_LIFETIME,
        DATABASE_PATH,
        LOGIN_MAX_ATTEMPTS,
        LOGIN_LOCKOUT_DURATIONS,
        LOGIN_ATTEMPT_WINDOW,
        MAX_CONCURRENT_SESSIONS,
        logger as _config_logger,
    )
    # 统一使用 config 模块的 logger，替换模块级 logger
    logger = _config_logger
except ImportError:
    # 兼容独立运行场景
    SESSION_LIFETIME = 3600
    REMEMBER_ME_LIFETIME = 30 * 24 * 3600
    DEFAULT_DB_PATH = os.path.join(os.getcwd(), "data", "telegram_imagebed.db")
    DATABASE_PATH = DEFAULT_DB_PATH
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCKOUT_DURATIONS = [300, 900, 1800]
    LOGIN_ATTEMPT_WINDOW = 900
    MAX_CONCURRENT_SESSIONS = 3


# ===================== CSRF 保护 =====================

_CSRF_TOKEN_LENGTH = 32




# ===================== 登录速率限制器（SQLite 持久化 + 内存热缓存） =====================
# 持久化到 login_attempts 表，进程重启后锁定状态不丢失
# 内存热缓存（LRU，最大 1000 条）减少 DB 读取

from collections import OrderedDict
import threading

_LOGIN_CACHE_MAX = 1000
_login_cache: OrderedDict[str, dict] = OrderedDict()
_login_cache_lock = threading.Lock()

# TTL: 超过此秒数的非锁定记录在清理时删除（1 小时 = 3600 秒）
_LOGIN_ATTEMPT_TTL = 3600


def _login_attempts_from_db(ip: str) -> dict | None:
    """从 SQLite 读取 IP 的登录尝试记录"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ip, failed_count, locked_until, lockout_level, last_attempt "
                "FROM login_attempts WHERE ip = ?",
                (ip,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                'attempts': row['failed_count'],
                'locked_until': row['locked_until'],
                'lockout_level': row['lockout_level'],
                'last_attempt': row['last_attempt'],
            }
    except sqlite3.Error as e:
        logger.debug(f"读取 login_attempts 失败: {e}")
        return None


def _login_attempts_upsert_db(ip: str, data: dict) -> None:
    """写入/更新 SQLite 中的登录尝试记录"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO login_attempts (ip, failed_count, locked_until, lockout_level, last_attempt) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(ip) DO UPDATE SET "
                "failed_count = excluded.failed_count, "
                "locked_until = excluded.locked_until, "
                "lockout_level = excluded.lockout_level, "
                "last_attempt = excluded.last_attempt",
                (
                    ip,
                    data.get('attempts', 0),
                    data.get('locked_until', 0),
                    data.get('lockout_level', 0),
                    data.get('last_attempt', 0),
                )
            )
    except sqlite3.Error as e:
        logger.warning(f"写入 login_attempts 失败: {e}")


def _login_attempts_del_db(ip: str) -> None:
    """从 SQLite 删除 IP 的登录尝试记录"""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
    except sqlite3.Error as e:
        logger.debug(f"删除 login_attempts 失败: {e}")


def _login_attempts_cleanup_db() -> int:
    """清理过期的登录记录（非锁定 + last_attempt 超过 TTL）

    使用 AND 语义：仅当锁定已过期 且 最后尝试时间超过 1 小时才删除。
    这保证刚解锁的记录（locked_until 刚过但 last_attempt 在窗口内）
    不会被误删，设计上保守但安全。
    """
    now = time.time()
    cutoff = now - _LOGIN_ATTEMPT_TTL
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                # AND: locked_until < now（锁定已过期） AND last_attempt < cutoff（最后尝试超过 TTL）
                "DELETE FROM login_attempts WHERE locked_until < ? AND last_attempt < ?",
                (now, cutoff)
            )
            return cursor.rowcount
    except sqlite3.Error as e:
        logger.debug(f"清理 login_attempts 失败: {e}")
        return 0


def _get_login_info(ip: str) -> dict | None:
    """
    获取 IP 的登录追踪信息，优先读缓存，miss 时查 DB 并回填缓存
    """
    with _login_cache_lock:
        info = _login_cache.get(ip)
        if info is not None:
            # LRU: move to end
            _login_cache.move_to_end(ip)
            return info

    # 缓存未命中，查 DB
    info = _login_attempts_from_db(ip)
    if info is not None:
        with _login_cache_lock:
            if len(_login_cache) >= _LOGIN_CACHE_MAX:
                _login_cache.popitem(last=False)  # 淘汰最旧
            _login_cache[ip] = info
    return info


def _set_login_info(ip: str, info: dict | None) -> None:
    """
    写入登录追踪信息：DB 写穿 + 缓存更新
    info=None 表示删除该条目（登录成功时调用）
    """
    # 先写 DB
    if info is None:
        _login_attempts_del_db(ip)
    else:
        _login_attempts_upsert_db(ip, info)

    # 更新缓存
    with _login_cache_lock:
        if info is None:
            _login_cache.pop(ip, None)
        else:
            if len(_login_cache) >= _LOGIN_CACHE_MAX:
                _login_cache.popitem(last=False)
            _login_cache[ip] = info


def _get_client_ip(req) -> str:
    """获取真实客户端 IP（兼容 Cloudflare 与反向代理）"""
    return get_client_ip(req)


def _cleanup_expired_trackers():
    """清理过期的登录追踪记录（DB + 缓存）"""
    _login_attempts_cleanup_db()

    now = time.time()
    with _login_cache_lock:
        expired = [
            ip for ip, info in _login_cache.items()
            if now - info.get('last_attempt', 0) > LOGIN_ATTEMPT_WINDOW
            and now > info.get('locked_until', 0)
        ]
        for ip in expired:
            del _login_cache[ip]


_CLEANUP_THREAD_STARTED = False
_CLEANUP_THREAD_LOCK = threading.Lock()


def _start_periodic_cleanup() -> None:
    """启动后台定时清理线程（每 5 分钟清理一次过期登录追踪记录）"""
    global _CLEANUP_THREAD_STARTED
    with _CLEANUP_THREAD_LOCK:
        if _CLEANUP_THREAD_STARTED:
            return
        _CLEANUP_THREAD_STARTED = True

    def _periodic_cleanup_worker() -> None:
        while True:
            try:
                time.sleep(300)  # 5 分钟间隔
                _cleanup_expired_trackers()
            except Exception:
                logger.debug("定时清理线程异常", exc_info=True)

    t = threading.Thread(target=_periodic_cleanup_worker, daemon=True)
    t.start()
    logger.info("登录追踪定时清理线程已启动（间隔 5 分钟）")


def _check_login_allowed(ip: str, username: str = '') -> tuple[bool, int, int]:
    """
    检查 IP 是否允许登录（支持用户名+IP 双重维度）
    返回: (allowed, retry_after_seconds, remaining_attempts)
    """
    _cleanup_expired_trackers()
    info = _get_login_info(ip)
    if not info:
        return True, 0, LOGIN_MAX_ATTEMPTS

    now = time.time()

    # 检查是否在锁定期内
    locked_until = info.get('locked_until', 0)
    if now < locked_until:
        retry_after = int(locked_until - now) + 1
        return False, retry_after, 0

    # 检查失败计数窗口是否已过期（自动重置）
    if now - info.get('last_attempt', 0) > LOGIN_ATTEMPT_WINDOW:
        _set_login_info(ip, None)
        return True, 0, LOGIN_MAX_ATTEMPTS

    # 用户名维度检查：统计该用户名在窗口期内跨 IP 的失败总数
    if username:
        uname_attempts = _get_username_total_failures(username)
        remaining_by_ip = max(0, LOGIN_MAX_ATTEMPTS - info.get('attempts', 0))
        remaining_by_user = max(0, LOGIN_MAX_ATTEMPTS - uname_attempts)
        remaining = min(remaining_by_ip, remaining_by_user)
    else:
        remaining = max(0, LOGIN_MAX_ATTEMPTS - info.get('attempts', 0))

    return True, 0, remaining


_USERNAME_FAIL_KEY_PREFIX = "uname:"


def _get_username_total_failures(username: str) -> int:
    """统计指定用户名在窗口期内的总失败次数（跨所有 IP）"""
    now = time.time()
    cutoff = now - LOGIN_ATTEMPT_WINDOW
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SUM(failed_count) FROM login_attempts "
                "WHERE ip LIKE ? AND last_attempt > ?",
                (f"{_USERNAME_FAIL_KEY_PREFIX}{username}\t%", cutoff)
            )
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] else 0
    except sqlite3.Error:
        return 0


def _record_username_failure(username: str, ip: str) -> None:
    """记录用户名维度失败（跨 IP 追踪同一用户名的失败尝试）"""
    now = time.time()
    key = f"{_USERNAME_FAIL_KEY_PREFIX}{username}\t{ip}"
    info = _get_login_info(key)
    if not info:
        info = {'attempts': 1, 'locked_until': 0, 'lockout_level': 0, 'last_attempt': now}
    else:
        info['attempts'] = info.get('attempts', 0) + 1
        info['last_attempt'] = now
    _set_login_info(key, info)


def _clear_username_failures(username: str) -> None:
    """登录成功后清除该用户名下所有 IP 的失败记录"""
    try:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM login_attempts WHERE ip LIKE ?",
                (f"{_USERNAME_FAIL_KEY_PREFIX}{username}\t%",)
            )
    except sqlite3.Error as e:
        logger.warning(f"清除用户名失败记录失败: {e}")
    with _login_cache_lock:
        prefix = f"{_USERNAME_FAIL_KEY_PREFIX}{username}\t"
        keys_to_del = [k for k in _login_cache if k.startswith(prefix)]
        for k in keys_to_del:
            del _login_cache[k]


def _record_login_failure(ip: str) -> None:
    """记录登录失败，累加计数，达到阈值时触发渐进式锁定"""
    now = time.time()
    info = _get_login_info(ip)

    if not info:
        info = {
            'attempts': 1,
            'locked_until': 0,
            'lockout_level': 0,
            'last_attempt': now,
        }
        _set_login_info(ip, info)
        return

    info['attempts'] = info.get('attempts', 0) + 1
    info['last_attempt'] = now

    # 达到阈值 → 触发锁定
    if info['attempts'] >= LOGIN_MAX_ATTEMPTS:
        level = info.get('lockout_level', 0)
        duration = LOGIN_LOCKOUT_DURATIONS[min(level, len(LOGIN_LOCKOUT_DURATIONS) - 1)]
        info['locked_until'] = now + duration
        info['lockout_level'] = min(level + 1, len(LOGIN_LOCKOUT_DURATIONS) - 1)
        info['attempts'] = 0  # 重置计数，解锁后重新开始计数

    _set_login_info(ip, info)


def _record_login_success(ip: str) -> None:
    """登录成功后清除该 IP 的失败记录（DB + 缓存）"""
    _set_login_info(ip, None)


# ===================== 密码强度校验 =====================
def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    校验密码强度
    返回: (valid, message)

    要求: ≥12 字符、含大小写字母、含数字、含特殊字符
    """
    if not password or len(password) < 12:
        return False, '密码长度至少需要12个字符'
    if not re.search(r'[a-z]', password):
        return False, '密码必须包含小写字母'
    if not re.search(r'[A-Z]', password):
        return False, '密码必须包含大写字母'
    if not re.search(r'[0-9]', password):
        return False, '密码必须包含数字'
    if not re.search(r'[^a-zA-Z0-9]', password):
        return False, '密码必须包含特殊字符（如 !@#$% 等）'
    return True, ''


# ===================== 安全审计日志 =====================
def _read_security_log() -> list:
    """读取安全日志，兼容旧 JSON 数组格式和新 JSONL 格式"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM admin_config WHERE key = 'security_log'")
        row = cursor.fetchone()

    if not row or not row[0]:
        return []

    raw = row[0].strip()
    if raw.startswith('['):
        # 旧格式：JSON 数组（迁移后自动转为 JSONL）
        return json.loads(raw)
    else:
        # 新格式：JSONL，每行一个事件
        return [json.loads(line) for line in raw.split('\n') if line.strip()]


def _log_security_event(event_type: str, ip: str, username: str = '', detail: str = '') -> None:
    """将安全事件以 JSONL 格式追加写入 admin_config（key=security_log，保留最近 200 条）

    使用 append-only JSONL 避免 O(n²) I/O 放大：
    - 旧方案：读全量 JSON → 解析 → 追加 → 序列化 → 写回（O(n) 读写量）
    - 新方案：读原始文本 → 截取末尾 199 行 → 追加 1 行 → 写回（O(1) 读写量）
    """
    try:
        entry = json.dumps({
            'type': event_type,
            'ip': ip,
            'username': username,
            'detail': detail,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }, ensure_ascii=False)

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM admin_config WHERE key = 'security_log'")
            row = cursor.fetchone()

            if row and row[0]:
                raw = row[0].strip()
                if raw.startswith('['):
                    # 旧格式迁移：解析旧数组，转为 JSONL
                    old_logs = json.loads(raw)
                    lines = [json.dumps(e, ensure_ascii=False) for e in old_logs[-199:]]
                else:
                    lines = raw.split('\n')[-199:] if raw else []
                lines.append(entry)
                new_value = '\n'.join(lines)
            else:
                new_value = entry

            cursor.execute(
                "INSERT OR REPLACE INTO admin_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                ('security_log', new_value)
            )
    except sqlite3.Error as e:
        logger.debug(f"写入安全审计日志失败: {e}")


# ===================== Session 并发控制 =====================

def _get_session_lifetime(remember_me: bool = False) -> int:
    """根据是否"记住我"返回对应的 session 有效期（秒）"""
    return REMEMBER_ME_LIFETIME if remember_me else SESSION_LIFETIME


def _safe_text(value: str, max_len: int = 128) -> str:
    return str(value or '').strip()[:max_len]


def _new_admin_session_id() -> str:
    return secrets.token_urlsafe(12)


# ===================== CSRF 保护（Double-Submit Cookie 模式） =====================

_CSRF_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def _generate_csrf_token() -> str:
    """生成 CSRF token"""
    return secrets.token_urlsafe(32)


def _set_csrf_cookie(response: "Response", token: str | None = None) -> "Response":
    """在响应中设置 csrf_token cookie（httponly=False 以允许前端 JS 读取）"""
    if token is None:
        token = _generate_csrf_token()
    try:
        secure = (
            request.is_secure
            or request.headers.get('X-Forwarded-Proto', '').lower() == 'https'
        )
    except RuntimeError:
        secure = False
    response.set_cookie(
        'csrf_token',
        token,
        httponly=False,   # 前端 JS 需要读取（Double-Submit Cookie 模式）
        samesite='Strict',
        secure=secure,
        max_age=86400,    # 24 小时
        path='/',
    )
    return response


def _guess_platform(user_agent: str) -> str:
    return parse_user_agent(user_agent).get('platform') or 'web'


def _get_admin_device_context(req) -> dict:
    ua = _safe_text(req.headers.get('User-Agent', ''), 512)
    parsed = parse_user_agent(ua)
    platform = _safe_text(req.headers.get('X-Platform', ''), 32) or parsed.get('platform') or 'web'
    device_name = normalize_device_name(_safe_text(req.headers.get('X-Device-Name', ''), 120), parsed)
    device_label = build_device_label(parsed.get('os_name'), parsed.get('browser_name'))
    device_id = _safe_text(req.headers.get('X-Device-Id', ''), 128)
    return {
        'user_agent': ua,
        'platform': platform,
        'device_name': device_name,
        'device_id': device_id,
        'os_name': parsed.get('os_name') or 'Unknown OS',
        'browser_name': parsed.get('browser_name') or 'Unknown Browser',
        'browser_version': parsed.get('browser_version') or '',
        'device_label': device_label,
    }


def _prune_and_migrate_sessions(sessions: list[dict], now: float | None = None) -> list[dict]:
    """清理过期项并补齐历史字段"""
    current = now if now is not None else time.time()
    normalized: list[dict] = []
    for raw in sessions or []:
        token = str(raw.get('token') or '').strip()
        if not token:
            continue
        try:
            login_time = float(raw.get('login_time') or current)
        except (ValueError, TypeError):
            login_time = current
        remember_me = bool(raw.get('remember_me', False))
        lifetime = _get_session_lifetime(remember_me)
        if current - login_time >= lifetime:
            continue

        try:
            last_active = float(raw.get('last_active') or login_time)
        except (ValueError, TypeError):
            last_active = login_time

        user_agent = _safe_text(raw.get('user_agent', ''), 512)
        parsed = parse_user_agent(user_agent)
        platform = _safe_text(raw.get('platform', ''), 32) or parsed.get('platform') or 'web'
        device_name = normalize_device_name(_safe_text(raw.get('device_name', ''), 120), parsed)
        device_id = _safe_text(raw.get('device_id', ''), 128)
        os_name = _safe_text(raw.get('os_name', ''), 64) or parsed.get('os_name') or 'Unknown OS'
        browser_name = _safe_text(raw.get('browser_name', ''), 64) or parsed.get('browser_name') or 'Unknown Browser'
        browser_version = _safe_text(raw.get('browser_version', ''), 32) or parsed.get('browser_version') or ''
        device_label = _safe_text(raw.get('device_label', ''), 120) or build_device_label(os_name, browser_name)

        normalized.append({
            'session_id': _safe_text(raw.get('session_id', ''), 64) or _new_admin_session_id(),
            'token': token,
            'ip': _safe_text(raw.get('ip', ''), 64),
            'login_time': login_time,
            'last_active': last_active,
            'remember_me': remember_me,
            'user_agent': user_agent,
            'platform': platform,
            'device_name': device_name,
            'device_id': device_id,
            'os_name': os_name,
            'browser_name': browser_name,
            'browser_version': browser_version,
            'device_label': device_label,
        })

    # 并发控制基于登录时间，从旧到新排序
    normalized.sort(key=lambda s: s.get('login_time', 0))
    return normalized


def _get_active_sessions() -> list[dict]:
    """从数据库读取活跃 session 列表"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM admin_config WHERE key = 'active_sessions'")
            row = cursor.fetchone()
            raw = json.loads(row[0]) if row else []
            return _prune_and_migrate_sessions(raw)
    except sqlite3.Error:
        return []


def _save_active_sessions(sessions: list[dict]) -> None:
    """保存活跃 session 列表到数据库"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO admin_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                ('active_sessions', json.dumps(sessions, ensure_ascii=False))
            )
    except sqlite3.Error as e:
        logger.warning(f"保存活跃 session 失败: {e}")


def _register_session(
    token: str,
    ip: str,
    remember_me: bool = False,
    *,
    user_agent: str = '',
    platform: str = '',
    device_name: str = '',
    device_id: str = '',
    os_name: str = '',
    browser_name: str = '',
    browser_version: str = '',
    device_label: str = '',
) -> None:
    """注册新 session，超出并发限制时踢掉最早的"""
    now = time.time()
    sessions = _prune_and_migrate_sessions(_get_active_sessions(), now)

    # 踢掉最早的 session（如果超出限制）
    kicked = []
    while len(sessions) >= MAX_CONCURRENT_SESSIONS:
        oldest = sessions.pop(0)
        kicked.append(oldest)

    # 记录被踢出的 session
    for s in kicked:
        _log_security_event(
            'session_kicked',
            s.get('ip', ''),
            detail=f"session_id={s.get('session_id', '')}, token={s.get('token', '')[:8]}..."
        )

    # 添加新 session
    sessions.append({
        'session_id': _new_admin_session_id(),
        'token': token,
        'ip': _safe_text(ip, 64),
        'login_time': now,
        'last_active': now,
        'remember_me': remember_me,
        'user_agent': _safe_text(user_agent, 512),
        'platform': _safe_text(platform, 32) or _guess_platform(user_agent),
        'device_name': _safe_text(device_name, 120),
        'device_id': _safe_text(device_id, 128),
        'os_name': _safe_text(os_name, 64),
        'browser_name': _safe_text(browser_name, 64),
        'browser_version': _safe_text(browser_version, 32),
        'device_label': _safe_text(device_label, 120),
    })

    _save_active_sessions(sessions)


def _update_session_activity(
    token: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    platform: str | None = None,
    device_name: str | None = None,
    device_id: str | None = None,
    os_name: str | None = None,
    browser_name: str | None = None,
    browser_version: str | None = None,
    device_label: str | None = None,
) -> None:
    """更新 session 的最后活跃时间，若不存在则自动补注册"""
    now = time.time()
    sessions = _prune_and_migrate_sessions(_get_active_sessions(), now)

    found = False
    for s in sessions:
        if s.get('token') == token:
            s['last_active'] = now
            if ip:
                s['ip'] = _safe_text(ip, 64)
            if user_agent:
                s['user_agent'] = _safe_text(user_agent, 512)
            if platform:
                s['platform'] = _safe_text(platform, 32)
            if device_name:
                s['device_name'] = _safe_text(device_name, 120)
            if device_id:
                s['device_id'] = _safe_text(device_id, 128)
            if os_name:
                s['os_name'] = _safe_text(os_name, 64)
            if browser_name:
                s['browser_name'] = _safe_text(browser_name, 64)
            if browser_version:
                s['browser_version'] = _safe_text(browser_version, 32)
            if device_label:
                s['device_label'] = _safe_text(device_label, 120)
            found = True
            break

    if not found:
        # 当前 session 不在列表中（功能上线前已登录），自动补注册
        fallback_ip = '0.0.0.0'
        try:
            fallback_ip = _get_client_ip(request)
        except RuntimeError:
            pass
        sessions.append({
            'session_id': _new_admin_session_id(),
            'token': token,
            'ip': _safe_text(ip or fallback_ip, 64),
            'login_time': now,
            'last_active': now,
            'remember_me': False,
            'user_agent': _safe_text(user_agent, 512),
            'platform': _safe_text(platform, 32) or _guess_platform(user_agent or ''),
            'device_name': _safe_text(device_name, 120),
            'device_id': _safe_text(device_id, 128),
            'os_name': _safe_text(os_name, 64),
            'browser_name': _safe_text(browser_name, 64),
            'browser_version': _safe_text(browser_version, 32),
            'device_label': _safe_text(device_label, 120),
        })

    _save_active_sessions(sessions)


def _remove_session(token: str = '', session_id: str = '') -> int:
    """移除指定 session（按 token 或 session_id）"""
    sessions = _get_active_sessions()
    if not token and not session_id:
        return 0
    new_sessions = [
        s for s in sessions
        if not ((token and s.get('token') == token) or (session_id and s.get('session_id') == session_id))
    ]
    removed = len(sessions) - len(new_sessions)
    if removed > 0:
        _save_active_sessions(new_sessions)
    return removed


def _get_config_status_from_db() -> dict:
    """从数据库读取配置状态（使用 system_settings 表）"""
    cdn_enabled = False
    cdn_monitor_enabled = False
    cdn_domain = ''

    try:
        from .database import get_system_setting
        cdn_enabled = str(get_system_setting('cdn_enabled') or '0') == '1'
        cdn_monitor_enabled = str(get_system_setting('cdn_monitor_enabled') or '0') == '1'
        cdn_domain = str(get_system_setting('cloudflare_cdn_domain') or '').strip()
        group_upload_admin_only = str(get_system_setting('group_upload_admin_only') or '0') == '1'
    except sqlite3.Error as e:
        logger.warning(f"从数据库读取系统设置失败: {e}")
        group_upload_admin_only = False

    # CDN 监控只有在 CDN 启用时才有意义
    cdn_monitor_display = '已启用' if (cdn_enabled and cdn_monitor_enabled) else '已关闭'

    return {
        'cdnStatus': '已启用' if cdn_enabled else '未启用',
        'cdnDomain': cdn_domain if cdn_domain else '未配置',
        'uptime': '运行中',
        'groupUpload': '仅管理员' if group_upload_admin_only else '已开放',
        'cdnMonitor': cdn_monitor_display
    }

def init_admin_config() -> None:
    """初始化管理员配置表（在主数据库中）"""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

def get_admin_config() -> dict:
    """获取管理员配置"""
    init_admin_config()

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM admin_config WHERE key = 'username'")
        username = cursor.fetchone()
        username = username[0] if username else ''

        cursor.execute("SELECT value FROM admin_config WHERE key = 'password_hash'")
        password_hash = cursor.fetchone()

        return {
            'username': username,
            'password_status': '已设置' if password_hash else '未设置（需通过 /setup 初始化）',
            'session_lifetime': SESSION_LIFETIME
        }

def verify_admin_password(username: str, password: str) -> bool:
    """验证管理员密码"""
    from werkzeug.security import check_password_hash

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM admin_config WHERE key = 'username'")
        stored_username = cursor.fetchone()
        if not stored_username or stored_username[0] != username:
            return False

        cursor.execute("SELECT value FROM admin_config WHERE key = 'password_hash'")
        stored_hash = cursor.fetchone()

        if not stored_hash:
            return False

        # 使用 werkzeug.security 验证密码
        # 兼容旧的 sha256 哈希格式
        hash_value = stored_hash[0]
        if hash_value.startswith('pbkdf2:'):
            return check_password_hash(hash_value, password)
        else:
            # 兼容旧格式（sha256）
            if hash_value == hashlib.sha256(password.encode()).hexdigest():
                # 旧格式验证成功，自动升级为 pbkdf2
                try:
                    update_admin_credentials(new_password=password)
                    logger.debug(f"已自动将管理员 {username} 的密码哈希从 SHA256 升级为 pbkdf2")
                except sqlite3.Error as e:
                    logger.warning(f"密码哈希自动升级失败（不影响登录）: {e}")
                return True
            return False

def update_admin_credentials(new_username: str | None = None, new_password: str | None = None) -> bool:
    """更新管理员凭据"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            if new_username:
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_config (key, value, updated_at)
                    VALUES ('username', ?, CURRENT_TIMESTAMP)
                ''', (new_username,))

            if new_password:
                # 使用 werkzeug.security 进行安全的密码哈希
                from werkzeug.security import generate_password_hash
                password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_config (key, value, updated_at)
                    VALUES ('password_hash', ?, CURRENT_TIMESTAMP)
                ''', (password_hash,))

        return True
    except sqlite3.Error as e:
        logger.error(f"更新管理员凭据失败: {e}")
        return False

class _AutoSecureSessionInterface(SecureCookieSessionInterface):
    """自动根据请求协议设置 cookie Secure 标记的 Session 接口
    HTTPS 请求 → Secure=True（cookie 仅通过 HTTPS 发送）
    HTTP 请求 → Secure=False（cookie 可通过 HTTP 发送）
    同时兼容反向代理（X-Forwarded-Proto）"""

    def get_cookie_secure(self, app):
        try:
            return (
                request.is_secure
                or request.headers.get('X-Forwarded-Proto', '').lower() == 'https'
            )
        except RuntimeError:
            # 请求上下文之外
            return False


def configure_admin_session(app: "Flask") -> None:
    """配置管理员会话"""
    app.session_interface = _AutoSecureSessionInterface()
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False  # 由 _AutoSecureSessionInterface 动态覆盖
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_LIFETIME)

    @app.before_request
    def _dynamic_session_lifetime():
        """根据 session 中的 _remember_me 标记动态调整 session 有效期，并实现活跃续期"""
        if session.get('admin_logged_in'):
            remember_me = session.get('_remember_me', False)
            lifetime = _get_session_lifetime(remember_me)
            app.permanent_session_lifetime = timedelta(seconds=lifetime)
            # 标记 session 已修改，使 Flask 重新设置 cookie 过期时间，实现活跃续期
            session.modified = True

# 添加登录验证装饰器
def login_required(f: "Callable") -> "Callable":
    """需要登录的装饰器（CSRF 由蓝图级 before_request 统一处理）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session or not session['admin_logged_in']:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('admin_login'))

        # CSRF 保护已由蓝图级 before_request (_csrf_protect) 统一处理

        # 检查当前 token 是否仍在活跃 session 列表中（被踢出则拒绝）
        token = session.get('admin_token')
        if token:
            active = _get_active_sessions()
            if active and not any(s.get('token') == token for s in active):
                # token 已被踢出，清除本地 session
                session.pop('admin_logged_in', None)
                session.pop('admin_username', None)
                session.pop('admin_token', None)
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Session revoked', 'kicked': True}), 401
                return redirect(url_for('admin_login'))
            device_ctx = _get_admin_device_context(request)
            _update_session_activity(
                token,
                ip=_get_client_ip(request),
                user_agent=device_ctx['user_agent'],
                platform=device_ctx['platform'],
                device_name=device_ctx['device_name'],
                device_id=device_ctx['device_id'],
                os_name=device_ctx['os_name'],
                browser_name=device_ctx['browser_name'],
                browser_version=device_ctx['browser_version'],
                device_label=device_ctx['device_label'],
            )

        return f(*args, **kwargs)
    return decorated_function


def init_database_admin_update(DATABASE_PATH: str) -> None:
    """为管理功能更新数据库索引"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # 检查并添加新列
            cursor.execute("PRAGMA table_info(file_storage)")
            columns = [column[1] for column in cursor.fetchall()]

            # 添加缺失的列
            if 'is_group_upload' not in columns:
                logger.info("管理模块：添加 is_group_upload 列")
                cursor.execute('ALTER TABLE file_storage ADD COLUMN is_group_upload BOOLEAN DEFAULT 0')

            if 'group_message_id' not in columns:
                logger.info("管理模块：添加 group_message_id 列")
                cursor.execute('ALTER TABLE file_storage ADD COLUMN group_message_id INTEGER')

            if 'group_chat_id' not in columns:
                logger.info("管理模块：添加 group_chat_id 列")
                cursor.execute('ALTER TABLE file_storage ADD COLUMN group_chat_id INTEGER')

            # 添加文件名索引以加速搜索
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_original_filename
                ON file_storage(original_filename)
            ''')

            # 添加额外的索引以优化管理查询
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON file_storage(created_at DESC)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_file_size ON file_storage(file_size)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_group_upload ON file_storage(is_group_upload)
            ''')

        logger.info("管理功能数据库索引创建完成")
    except sqlite3.Error as e:
        logger.error(f"创建管理索引失败: {e}")

def register_admin_routes(app: "Flask", DATABASE_PATH: str, get_all_files_count, get_total_size, add_cache_headers) -> None:
    """注册管理员路由（薄封装）

    管理路由已迁移到 api/admin_*.py 子模块（通过 admin_bp 蓝图注册）。
    此函数保留兼容调用，仅执行 session 配置和数据库索引初始化。
    """
    # 配置管理员 session
    configure_admin_session(app)

    # 初始化管理数据库索引
    init_database_admin_update(DATABASE_PATH)

    # 启动定时清理过期登录追踪的后台线程
    _start_periodic_cleanup()

    logger.info("管理员路由注册完成（已迁移到 Blueprint 子模块）")
