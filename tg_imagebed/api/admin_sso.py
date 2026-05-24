#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员路由 - 画集域名 SSO 回调

从 admin_module.register_admin_routes 迁移出来。
"""
import ipaddress
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from flask import request, jsonify, session, redirect

from . import admin_bp
from ..config import logger
from .. import admin_module


def _host_aliases(host: str) -> set:
    """为 loopback 主机名生成等价别名集合（避免 localhost/127.0.0.1 误判）"""
    h = (host or '').strip().lower()
    if not h:
        return set()
    aliases = {h}
    if h == 'localhost':
        aliases.update({'127.0.0.1', '::1'})
    elif h in {'127.0.0.1', '::1'}:
        aliases.update({'localhost', '127.0.0.1', '::1'})
    return aliases


def _append_query_param(url: str, key: str, value: str) -> str:
    """在 URL 中追加查询参数"""
    if url.startswith('/'):
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}{key}={value}"
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs[key] = [value]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment
    ))


# ============ 画集 SSO Token 生成 ============

@admin_bp.route('/api/admin/gallery-auth-token', methods=['POST'])
@admin_module.login_required
def admin_gallery_auth_token():
    """生成画集域名 SSO 一次性 token（60秒有效）"""
    try:
        username = session.get('admin_username', 'admin')
        token = admin_module.generate_gallery_auth_token(username)
        return jsonify({'success': True, 'data': {'token': token}})
    except Exception as e:
        logger.error(f"生成画集 SSO token 失败: {e}")
        return jsonify({'success': False, 'error': '生成 token 失败'}), 500


# ============ 画集 SSO 回调 ============

@admin_bp.route('/api/admin/gallery-sso-callback', methods=['GET'])
def admin_gallery_sso_callback():
    """主站 SSO 回调：检查 session，生成 token 并重定向回画集站点"""
    from ..database.domains import get_active_gallery_domains, get_default_domain

    return_url = request.args.get('return_url', '')

    if not return_url:
        return jsonify({'success': False, 'error': '缺少 return_url 参数'}), 400

    if return_url.startswith('/'):
        pass  # 相对路径，安全
    elif return_url.startswith('http://') or return_url.startswith('https://'):
        parsed = urlparse(return_url)
        target_host = parsed.hostname
        if not target_host:
            return jsonify({'success': False, 'error': 'return_url 无效'}), 400

        allowed_domains = set()
        gallery_domains = get_active_gallery_domains()
        for d in gallery_domains:
            allowed_domains.update(_host_aliases(d['domain']))

        default_domain = get_default_domain()
        if default_domain:
            allowed_domains.update(_host_aliases(default_domain['domain']))

        try:
            from ..database import get_system_setting
            saved_main_url = get_system_setting('gallery_sso_main_url')
            if saved_main_url:
                _parsed_main = urlparse(saved_main_url)
                if _parsed_main.hostname:
                    allowed_domains.update(_host_aliases(_parsed_main.hostname))
        except Exception:
            pass

        try:
            req_host = (
                request.headers.get('X-Forwarded-Host') or request.host or ''
            ).split(':')[0].lower()
            if req_host:
                allowed_domains.update(_host_aliases(req_host))
        except Exception:
            pass

        _is_private = False
        try:
            _is_private = ipaddress.ip_address(target_host).is_private
        except ValueError:
            pass

        target_aliases = _host_aliases(target_host)
        if not _is_private and target_aliases.isdisjoint(allowed_domains):
            logger.warning(f"SSO 回调 return_url 域名不合法: {target_host}")
            return jsonify({'success': False, 'error': 'return_url 域名不合法'}), 400
    else:
        return jsonify({'success': False, 'error': 'return_url 格式无效'}), 400

    if session.get('admin_logged_in'):
        try:
            from ..utils import get_domain
            from ..database import update_system_setting
            main_url = get_domain(request)
            update_system_setting('gallery_sso_main_url', main_url)
        except Exception:
            pass
        username = session.get('admin_username', 'admin')
        token = admin_module.generate_gallery_auth_token(username)
        final_url = _append_query_param(return_url, 'auth_token', token)
        return redirect(final_url)
    else:
        final_url = _append_query_param(return_url, 'sso_failed', '1')
        return redirect(final_url)
