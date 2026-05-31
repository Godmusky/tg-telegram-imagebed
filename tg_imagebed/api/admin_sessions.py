#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员路由 - 会话管理与安全审计

从 admin_module.register_admin_routes 迁移出来。
"""
import json
import time
from datetime import datetime

from flask import request, jsonify, session

from . import admin_bp
from .admin_helpers import _admin_options
from ..config import logger
from ..utils import add_cache_headers
from ..database.connection import get_connection
from .. import admin_module


# ============ 安全审计日志 ============

@admin_bp.route('/api/admin/security-log', methods=['GET', 'OPTIONS'])
@admin_module.login_required
def admin_security_log():
    """获取安全审计日志"""
    if request.method == 'OPTIONS':
        return _admin_options('GET, OPTIONS')

    try:
        logs = admin_module._read_security_log()
        logs.reverse()
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        logger.error(f"获取安全日志失败: {e}")
        return jsonify({'success': False, 'error': '获取安全日志失败'}), 500


# ============ 活跃会话 ============

@admin_bp.route('/api/admin/active-sessions', methods=['GET', 'OPTIONS'])
@admin_module.login_required
def admin_active_sessions():
    """获取当前活跃 Session 列表"""
    if request.method == 'OPTIONS':
        return _admin_options('GET, OPTIONS')

    try:
        current_token = session.get('admin_token', '')
        if current_token:
            ctx = admin_module._get_admin_device_context(request)
            admin_module._update_session_activity(
                current_token,
                ip=admin_module._get_client_ip(request),
                user_agent=ctx['user_agent'],
                platform=ctx['platform'],
                device_name=ctx['device_name'],
                device_id=ctx['device_id'],
                os_name=ctx['os_name'],
                browser_name=ctx['browser_name'],
                browser_version=ctx['browser_version'],
                device_label=ctx['device_label'],
            )
            sessions = admin_module._get_active_sessions()
        else:
            sessions = admin_module._get_active_sessions()
            admin_module._save_active_sessions(sessions)

        from .. import admin_module as am
        current_session_id = ''
        result = []
        for s in sorted(sessions, key=lambda item: item.get('last_active', 0), reverse=True):
            login_ts = s.get('login_time', 0)
            last_ts = s.get('last_active', 0)
            user_agent = s.get('user_agent', '')
            parsed = am.parse_user_agent(user_agent)
            os_name = s.get('os_name') or parsed.get('os_name') or 'Unknown OS'
            browser_name = (
                s.get('browser_name') or parsed.get('browser_name') or 'Unknown Browser'
            )
            browser_version = s.get('browser_version') or parsed.get('browser_version') or ''
            device_label = (
                s.get('device_label')
                or am.build_device_label(os_name, browser_name)
            )
            is_current = s.get('token', '') == current_token
            if is_current:
                current_session_id = s.get('session_id', '')
            result.append({
                'session_id': s.get('session_id', ''),
                'token_prefix': s.get('token', '')[:8] + '...',
                'ip_address': s.get('ip', ''),
                'device_name': am.normalize_device_name(s.get('device_name'), parsed),
                'device_label': device_label,
                'os_name': os_name,
                'browser_name': browser_name,
                'browser_version': browser_version,
                'platform': s.get('platform') or parsed.get('platform') or 'unknown',
                'user_agent': user_agent,
                'device_id': s.get('device_id', ''),
                'login_time': (
                    datetime.fromtimestamp(login_ts).strftime('%Y-%m-%d %H:%M:%S')
                    if login_ts else ''
                ),
                'last_active': (
                    datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S')
                    if last_ts else ''
                ),
                'is_current': is_current,
                'remember_me': bool(s.get('remember_me', False)),
            })

        if current_token and not any(item.get('is_current') for item in result):
            ctx = admin_module._get_admin_device_context(request)
            fallback_session_id = f"current-{current_token[:8]}"
            result.insert(0, {
                'session_id': fallback_session_id,
                'token_prefix': current_token[:8] + '...',
                'ip_address': admin_module._get_client_ip(request),
                'device_name': ctx.get('device_name') or ctx.get('device_label') or 'current-browser',
                'device_label': (
                    ctx.get('device_label')
                    or am.build_device_label(ctx.get('os_name'), ctx.get('browser_name'))
                ),
                'os_name': ctx.get('os_name') or 'Unknown OS',
                'browser_name': ctx.get('browser_name') or 'Unknown Browser',
                'browser_version': ctx.get('browser_version') or '',
                'platform': ctx.get('platform') or 'web',
                'user_agent': ctx.get('user_agent') or '',
                'device_id': ctx.get('device_id') or '',
                'login_time': '',
                'last_active': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'is_current': True,
                'remember_me': bool(session.get('remember_me')),
            })
            current_session_id = fallback_session_id

        return jsonify({
            'success': True,
            'data': {
                'sessions': result,
                'count': len(result),
                'current_session_id': current_session_id
            }
        })
    except Exception as e:
        logger.error(f"获取活跃 Session 失败: {e}")
        return jsonify({'success': False, 'error': '获取失败'}), 500


# ============ 会话心跳 ============

@admin_bp.route('/api/admin/session-heartbeat', methods=['POST', 'OPTIONS'])
@admin_module.login_required
def admin_session_heartbeat():
    """刷新管理员当前会话活跃时间"""
    if request.method == 'OPTIONS':
        return _admin_options('POST, OPTIONS')

    try:
        token = session.get('admin_token', '')
        if not token:
            return jsonify({'success': False, 'error': '未登录'}), 401
        ctx = admin_module._get_admin_device_context(request)
        admin_module._update_session_activity(
            token,
            ip=admin_module._get_client_ip(request),
            user_agent=ctx['user_agent'],
            platform=ctx['platform'],
            device_name=ctx['device_name'],
            device_id=ctx['device_id'],
            os_name=ctx['os_name'],
            browser_name=ctx['browser_name'],
            browser_version=ctx['browser_version'],
            device_label=ctx['device_label'],
        )
        return jsonify({
            'success': True,
            'data': {'server_time': int(time.time())}
        })
    except Exception as e:
        logger.error(f"管理员会话心跳失败: {e}")
        return jsonify({'success': False, 'error': '刷新失败'}), 500


# ============ 踢出会话（精确） ============

@admin_bp.route('/api/admin/revoke-session', methods=['POST', 'OPTIONS'])
@admin_module.login_required
def admin_revoke_session():
    """按 session_id 精确踢出指定会话"""
    if request.method == 'OPTIONS':
        return _admin_options('POST, OPTIONS')

    data = request.get_json(silent=True) or {}
    session_id = admin_module._safe_text(data.get('session_id', ''), 64)
    if not session_id:
        return jsonify({'success': False, 'error': '缺少 session_id'}), 400
    try:
        sessions = admin_module._get_active_sessions()
        current_token = session.get('admin_token', '')
        target = next(
            (s for s in sessions if s.get('session_id') == session_id), None
        )
        if not target:
            return jsonify({'success': False, 'error': '会话不存在'}), 404
        if target.get('token') == current_token:
            return jsonify({'success': False, 'error': '不能踢出当前会话'}), 400
        removed = admin_module._remove_session(session_id=session_id)
        if removed > 0:
            ip = admin_module._get_client_ip(request)
            admin_module._log_security_event(
                'session_kicked',
                ip,
                session.get('admin_username', ''),
                detail=f"手动踢出 session_id={session_id}"
            )
        return jsonify({
            'success': True, 'kicked': removed, 'session_id': session_id
        })
    except Exception as e:
        logger.error(f"按 session_id 踢出失败: {e}")
        return jsonify({'success': False, 'error': '操作失败'}), 500


# ============ 踢出会话（兼容旧接口） ============

@admin_bp.route('/api/admin/kick-session', methods=['POST', 'OPTIONS'])
@admin_module.login_required
def admin_kick_session():
    """踢出指定 Session（兼容旧接口：优先 token_prefix，可选 session_id）"""
    if request.method == 'OPTIONS':
        return _admin_options('POST, OPTIONS')

    data = request.get_json(silent=True) or {}
    token_prefix = admin_module._safe_text(data.get('token_prefix', ''), 32)
    session_id = admin_module._safe_text(data.get('session_id', ''), 64)
    if not token_prefix and not session_id:
        return jsonify({'success': False, 'error': '缺少参数'}), 400

    try:
        sessions = admin_module._get_active_sessions()
        current_token = session.get('admin_token', '')

        target_session = None
        if session_id:
            target_session = next(
                (s for s in sessions if s.get('session_id') == session_id), None
            )
        elif token_prefix:
            target = token_prefix.rstrip('.')
            target_session = next(
                (s for s in sessions if s.get('token', '').startswith(target)), None
            )
            session_id = target_session.get('session_id', '') if target_session else ''

        if not target_session:
            return jsonify({'success': False, 'error': '会话不存在'}), 404
        if target_session.get('token') == current_token:
            return jsonify({'success': False, 'error': '不能踢出当前会话'}), 400

        kicked = admin_module._remove_session(session_id=session_id)

        if kicked > 0:
            ip = admin_module._get_client_ip(request)
            admin_module._log_security_event(
                'session_kicked',
                ip,
                session.get('admin_username', ''),
                detail=f"手动踢出 session_id={session_id}"
            )
        return jsonify({
            'success': True, 'kicked': kicked, 'session_id': session_id
        })
    except Exception as e:
        logger.error(f"踢出 Session 失败: {e}")
        return jsonify({'success': False, 'error': '操作失败'}), 500
