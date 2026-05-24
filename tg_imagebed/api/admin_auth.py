#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员路由 - 认证（登录/登出/状态检查/凭据更新）

从 admin_module.register_admin_routes 迁移出来。
使用 Flask session 而非 JWT。
"""
import secrets
from datetime import timedelta

from flask import request, jsonify, session

from . import admin_bp
from .admin_helpers import _admin_options
from ..config import logger
from .. import admin_module


# ============ CSRF Token ============

@admin_bp.route('/api/admin/csrf-token', methods=['GET', 'OPTIONS'])
def get_csrf_token():
    """获取 CSRF token（Double-Submit Cookie 模式）

    生成随机 token 并设置为 csrf_token cookie（httponly=False 以允许前端 JS 读取）。
    前端在管理后台加载时调用此端点获取 token，
    后续所有 state-changing 请求在 X-CSRF-Token 头中携带该 token。
    """
    if request.method == 'OPTIONS':
        return _admin_options('GET')
    token = admin_module._generate_csrf_token()
    resp = jsonify({'token': token})
    admin_module._set_csrf_cookie(resp, token)
    return resp


# ============ 登录状态检查 ============

@admin_bp.route('/api/admin/check', methods=['GET'])
def admin_check():
    """检查管理员登录状态"""
    if 'admin_logged_in' in session and session['admin_logged_in']:
        return jsonify({
            'authenticated': True,
            'username': session.get('admin_username', 'admin')
        })
    return jsonify({'authenticated': False})


# ============ 登录 ============

@admin_bp.route('/api/admin/login', methods=['POST'])
def admin_login_api():
    """管理员登录"""
    from ..config import SESSION_LIFETIME

    ip = admin_module._get_client_ip(request)

    allowed, retry_after, remaining = admin_module._check_login_allowed(ip)
    if not allowed:
        logger.warning(f"登录被锁定: IP={ip}, 剩余等待={retry_after}秒")
        admin_module._log_security_event(
            'login_locked', ip, detail=f"retry_after={retry_after}s"
        )
        response = jsonify({
            'success': False,
            'message': '登录尝试过多，请稍后再试',
            'locked': True,
            'retry_after': retry_after
        })
        return response, 429

    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    remember_me = bool(data.get('remember_me', False))

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

    if admin_module.verify_admin_password(username, password):
        admin_module._record_login_success(ip)

        session['admin_logged_in'] = True
        session['admin_username'] = username
        session['_remember_me'] = remember_me
        session.permanent = True

        # 注意：lifetime 的设置在 configure_admin_session 的 before_request 中动态处理
        # 此处不再通过 app.permanent_session_lifetime 设置（蓝图内无 app 引用）

        token = secrets.token_urlsafe(32)
        session['admin_token'] = token

        device_ctx = admin_module._get_admin_device_context(request)
        admin_module._register_session(
            token,
            ip,
            remember_me=remember_me,
            user_agent=device_ctx['user_agent'],
            platform=device_ctx['platform'],
            device_name=device_ctx['device_name'],
            device_id=device_ctx['device_id'],
            os_name=device_ctx['os_name'],
            browser_name=device_ctx['browser_name'],
            browser_version=device_ctx['browser_version'],
            device_label=device_ctx['device_label'],
        )

        admin_module._log_security_event('login_success', ip, username)
        logger.info(f"管理员登录成功: {username}")
        # token 仅存储于 httponly session cookie，不在响应体中明文回传
        return jsonify({
            'success': True,
            'data': {
                'username': username
            }
        })

    admin_module._record_login_failure(ip)
    admin_module._log_security_event('login_failed', ip, username)
    _, _, remaining = admin_module._check_login_allowed(ip)
    logger.warning(f"管理员登录失败: {username}, IP={ip}, 剩余尝试={remaining}")
    return jsonify({
        'success': False,
        'message': '用户名或密码错误',
    }), 401


# ============ 登出 ============

@admin_bp.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """管理员退出登录"""
    username = session.get('admin_username', 'unknown')
    token = session.get('admin_token')
    ip = admin_module._get_client_ip(request)

    if token:
        admin_module._remove_session(token)

    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    session.pop('admin_token', None)

    admin_module._log_security_event('logout', ip, username)
    logger.info(f"管理员退出登录: {username}")
    return jsonify({'success': True})


# ============ 更新凭据 ============

@admin_bp.route('/api/admin/update_credentials', methods=['POST'])
@admin_module.login_required
def admin_update_credentials():
    """更新管理员凭据"""
    data = request.get_json()
    new_username = data.get('username', '').strip()
    new_password = data.get('password', '').strip()

    if not new_username and not new_password:
        return jsonify({'success': False, 'error': '请提供新的用户名或密码'}), 400

    if new_username and len(new_username) < 3:
        return jsonify({'success': False, 'error': '用户名至少需要3个字符'}), 400

    if new_password:
        valid, msg = admin_module.validate_password_strength(new_password)
        if not valid:
            return jsonify({'success': False, 'error': msg}), 400

    if admin_module.update_admin_credentials(new_username, new_password):
        if new_username:
            session['admin_username'] = new_username

        ip = admin_module._get_client_ip(request)
        admin_module._log_security_event(
            'password_changed',
            ip,
            session.get('admin_username', ''),
            detail='username_changed' if new_username else 'password_changed'
        )

        return jsonify({
            'success': True,
            'message': '凭据更新成功',
            'updated_username': new_username is not None,
            'updated_password': new_password is not None
        })

    return jsonify({'success': False, 'error': '更新失败'}), 500
