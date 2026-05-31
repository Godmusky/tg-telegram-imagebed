#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片路由模块 - 图片访问、统计、信息 API
"""
import os
import time
import urllib.parse
from pathlib import Path
from datetime import datetime
from flask import request, jsonify, Response, send_file, redirect, send_from_directory

from . import images_bp
from ..config import (
    STATIC_FOLDER, STATIC_VERSION, START_TIME,
    logger
)
from ..database import (
    get_file_info, update_access_count, update_cdn_cache_status,
    get_stats, get_recent_uploads, update_file_path_in_db,
    get_system_setting, get_system_setting_int
)
from ..utils import (
    add_cache_headers, format_size, get_domain, get_image_domain, get_static_file_version
)
from ..services.cdn_service import cloudflare_cdn, get_monitor_queue_size
from ..storage.router import get_storage_router
from ..bot_control import get_bot_token_status


def _get_domain_mode():
    """获取域名模式配置（复用 utils 中的缓存逻辑）"""
    from ..utils import _get_effective_domain_settings
    domain, cdn_enabled = _get_effective_domain_settings()
    cdn_mode = bool(domain) and cdn_enabled
    return domain, cdn_enabled, cdn_mode


@images_bp.route('/')
def index():
    """返回主页"""
    index_path = os.path.join(STATIC_FOLDER, 'index.html')
    if os.path.exists(index_path):
        return send_file(index_path)
    else:
        return jsonify({
            'success': False,
            'error': '前端文件未找到',
            'message': '请先运行 cd frontend && npm run generate 构建前端',
            'api_base': get_domain(request)
        }), 404


@images_bp.route('/image/<encrypted_id>')
def get_image(encrypted_id):
    """获取图片 - CDN 重定向 + 存储后端代理 + ETag 缓存"""
    from ..storage.router import get_storage_router

    try:
        # 获取文件信息
        file_info = get_file_info(encrypted_id)
        if not file_info:
            return jsonify({'success': False, 'error': 'File not found'}), 404

        # 域名限制检查
        try:
            from ..database import is_allowed_image_domain
            host = (request.headers.get('X-Forwarded-Host') or request.host or '').split(':')[0].lower()
            if not is_allowed_image_domain(host):
                return jsonify({'success': False, 'error': 'Domain not allowed'}), 403
        except ImportError as e:
            logger.warning(f"域名验证模块导入失败，默认拒绝访问: {e}")
            return jsonify({'success': False, 'error': 'Domain not allowed'}), 403
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"域名验证参数异常，默认拒绝访问: {e}")
            return jsonify({'success': False, 'error': 'Domain not allowed'}), 403

        # CDN 重定向模式
        cdn_domain, _, cdn_mode = _get_domain_mode()
        cdn_redirect_enabled = str(get_system_setting('cdn_redirect_enabled') or '0') == '1'
        cdn_redirect_max_count = int(get_system_setting('cdn_redirect_max_count') or '2')
        cdn_redirect_delay = int(get_system_setting('cdn_redirect_delay') or '10')
        cdn_redirect_count = int(request.args.get('cdn_redirect', '0'))

        host = (request.headers.get('X-Forwarded-Host') or request.host or '').split(':')[0].lower()
        referer = (request.headers.get('Referer') or '').lower()
        is_from_cdn_domain = cdn_domain and host == cdn_domain
        is_referer_from_cdn = cdn_domain and cdn_domain in referer

        # 检查 CDN 是否已缓存
        cdn_cached = file_info.get('cdn_cached') or False

        if (
            cdn_redirect_enabled
            and not is_from_cdn_domain
            and not is_referer_from_cdn
            and cdn_redirect_count < cdn_redirect_max_count
            and cdn_domain
            and cdn_mode):
            # 重定向到 CDN
            cdn_url = f"https://{cdn_domain}/image/{encrypted_id}"
            # 触发 CDN 预热（异步）
            try:
                cdn_redirect_enabled_for_preheat = cdn_redirect_enabled
                if cloudflare_cdn.check_cdn_status(encrypted_id):
                    update_cdn_cache_status(encrypted_id, True)
                    cdn_cached = True
            except Exception:
                pass

            # 如果 CDN 已缓存，直接 301 重定向
            if cdn_cached:
                response = redirect(cdn_url, code=301)
                add_cache_headers(response, 'public', 31536000)
                return response

            # 未缓存时，302 临时重定向 + 触发预热
            response = redirect(f"{cdn_url}?cdn_redirect={cdn_redirect_count + 1}", code=302)
            return add_cache_headers(response, 'no-cache')

        # 原始路径：通过存储后端代理
        if cdn_mode:
            # CDN 模式但不需要重定向时（来自 CDN 的请求），设置长缓存
            cache_policy = 'public'
            cache_seconds = 31536000
        else:
            cache_policy = 'public'
            cache_seconds = 86400

        # 更新访问计数
        update_access_count(encrypted_id)

        # 通过存储后端获取图片（传递 Range 头支持断点续传/分块加载）
        router = get_storage_router()
        backend = router.get_backend_for_record(file_info)
        range_header = request.headers.get('Range')
        dl = backend.download(file_info=file_info, range_header=range_header)
        if not dl:
            return jsonify({'success': False, 'error': 'Image not available'}), 404

        mime_type = dl.content_type or file_info.get('mime_type') or 'application/octet-stream'
        original_filename = file_info.get('original_filename') or 'image'

        response = Response(dl.body, status=dl.status_code, content_type=mime_type)
        # 优先使用后端返回的 Content-Length（206 时为 range 实际大小），
        # 后端未提供时才用数据库中的完整 file_size
        if 'Content-Length' in dl.headers:
            response.headers['Content-Length'] = dl.headers['Content-Length']
        else:
            file_size = file_info.get('file_size') or 0
            response.headers['Content-Length'] = str(file_size)
        # 转发后端返回的 Content-Range（206 Partial Content 必须）
        if 'Content-Range' in dl.headers:
            response.headers['Content-Range'] = dl.headers['Content-Range']
        # RFC 5987 编码文件名，防止头部注入（\r\n 等控制字符）
        encoded_filename = urllib.parse.quote(original_filename, safe='')
        response.headers['Content-Disposition'] = f"inline; filename*=UTF-8''{encoded_filename}"
        return add_cache_headers(response, cache_policy, cache_seconds)

    except Exception as e:
        logger.error(f"获取图片失败: {encrypted_id}, 错误: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@images_bp.route('/api/recent')
def get_recent():
    """获取最近上传的图片"""
    limit = request.args.get('limit', 20, type=int)
    limit = max(1, min(50, limit))
    offset = request.args.get('offset', 0, type=int)
    offset = max(0, offset)

    try:
        files = get_recent_uploads(limit, offset)

        cdn_domain, _, cdn_mode = _get_domain_mode()
        base_url = get_image_domain(request).rstrip('/')
        result = []
        for f in files:
            encrypted_id = f.get('encrypted_id', '')
            file_data = {
                'id': encrypted_id,
                'url': f"{base_url}/image/{encrypted_id}",
                'filename': f.get('original_filename', '未知文件'),
                'size': f.get('file_size', 0),
                'upload_time': f.get('created_at', ''),
                'access_count': f.get('access_count', 0),
            }
            file_data['cdn_url'] = f"https://{cdn_domain}/image/{encrypted_id}" if cdn_mode else None
            result.append(file_data)

        response = jsonify({
            'success': True,
            'data': {
                'files': result,
                'limit': limit,
                'offset': offset,
                'has_more': len(result) >= limit,
            }
        })
        response.headers['Access-Control-Allow-Origin'] = '*'
        return add_cache_headers(response, 'no-cache')

    except Exception as e:
        logger.error(f"获取最近上传失败: {e}")
        response = jsonify({
            'success': False,
            'error': '获取列表失败',
            'data': {'files': [], 'limit': limit, 'offset': offset, 'has_more': False}
        })
        response.headers['Access-Control-Allow-Origin'] = '*'
        return add_cache_headers(response, 'no-cache'), 500


@images_bp.route('/api/stats')
def get_stats_api():
    """获取站点统计"""
    from ..utils import format_size
    import time
    from ..config import START_TIME

    stats = get_stats()
    max_file_size_mb = get_system_setting_int('max_file_size_mb', 20, minimum=1, maximum=100)
    
    # 今日上传数
    today_uploads = 0
    try:
        from ..database.connection import get_connection
        from datetime import datetime
        with get_connection() as conn:
            cursor = conn.cursor()
            today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            today_end = int(datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
            cursor.execute(
                "SELECT COUNT(*) FROM file_storage WHERE upload_time >= ? AND upload_time <= ?",
                (today_start, today_end)
            )
            today_uploads = cursor.fetchone()[0]
    except Exception:
        pass

    response = jsonify({
        'success': True,
        'data': {
            'totalFiles': str(stats.get('total_files', 0)),
            'totalSize': format_size(stats.get('total_size', 0)),
            'todayUploads': str(today_uploads),
            'uptime': str(int(time.time() - START_TIME)),
        }
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return add_cache_headers(response, 'public', 300)


@images_bp.route('/api/info')
def get_info():
    """获取公开服务器信息（不含敏感配置，内部配置需管理员认证）"""
    stats = get_stats()
    group_upload_admin_only = str(get_system_setting('group_upload_admin_only') or '0') == '1'
    group_upload_reply = str(get_system_setting('group_upload_reply') or '1') == '1'
    max_file_size_mb = get_system_setting_int('max_file_size_mb', 20, minimum=1, maximum=100)

    # 仅返回对外必要的公开信息
    # CDN 配置、内部存储类型、端口、版本号等敏感信息已移除
    # 如需内部配置，请使用管理员认证的 /api/admin/stats 端点
    response = jsonify({
        'domain': get_domain(request),
        'total_files': stats['total_files'],
        'group_uploads': stats['group_uploads'],
        'group_upload_admin_only': group_upload_admin_only,
        'group_upload_reply': group_upload_reply,
        'max_file_size': max_file_size_mb * 1024 * 1024,
    })

    response.headers['Access-Control-Allow-Origin'] = '*'
    return add_cache_headers(response, 'public', 300)


@images_bp.route('/api/health')
def health_check():
    """健康检查端点"""
    from ..database import get_connection

    cdn_domain, cdn_enabled, cdn_mode = _get_domain_mode()
    cdn_redirect_enabled = str(get_system_setting('cdn_redirect_enabled') or '0') == '1'

    uptime = int(time.time() - START_TIME)

    # 组件健康检查
    checks = {}

    # 1. 数据库
    try:
        with get_connection() as conn:
            conn.execute('SELECT 1')
        checks['database'] = {'healthy': True, 'error': None}
    except Exception as e:
        checks['database'] = {'healthy': False, 'error': str(e)}

    # 2. Bot Token
    token_status = get_bot_token_status()
    checks['bot_token'] = {
        'configured': bool(token_status.get('configured')),
        'source': token_status.get('source'),
    }

    # 3. 存储后端
    try:
        router = get_storage_router()
        backend_name = router.get_active_backend_name()
        backend = router.get_backend(backend_name)
        backend_healthy = backend.healthcheck()
        checks['storage'] = {
            'healthy': backend_healthy,
            'backend': backend_name,
            'error': None if backend_healthy else '健康检查失败',
        }
    except Exception as e:
        checks['storage'] = {'healthy': False, 'backend': None, 'error': str(e)}

    # 4. 前端构建
    index_path = os.path.join(STATIC_FOLDER, 'index.html')
    frontend_ready = os.path.isfile(index_path)
    checks['frontend'] = {
        'ready': frontend_ready,
        'path': STATIC_FOLDER if frontend_ready else None,
    }

    all_healthy = all(
        c.get('healthy', True) if 'healthy' in c else True
        for c in checks.values()
    )

    response = jsonify({
        'status': 'healthy' if all_healthy else 'degraded',
        'uptime_seconds': uptime,
        'timestamp': int(time.time()),
        'base_url': get_domain(request),
        'cdn_enabled': cdn_enabled,
        'cdn_mode': cdn_mode,
        'cloudflare_cdn': bool(cdn_domain),
        'cdn_redirect_enabled': cdn_redirect_enabled,
        'version': STATIC_VERSION,
        'checks': checks,
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return add_cache_headers(response, 'no-cache')


@images_bp.route('/robots.txt')
def robots():
    """提供 robots.txt"""
    robots_content = f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /admin

Sitemap: {get_domain(request)}/sitemap.xml
"""
    response = Response(robots_content, mimetype='text/plain')
    return add_cache_headers(response, 'public', 86400)


@images_bp.route('/manifest.json')
def manifest():
    """提供 PWA manifest"""
    manifest_data = {
        "name": "Telegram 云图床",
        "short_name": "云图床",
        "description": "基于Telegram云存储的免费图床服务",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#6366f1",
    }
    response = jsonify(manifest_data)
    return add_cache_headers(response, 'public', 86400)


def _decode_recursive(path: str, max_depth: int = 5) -> list:
    """递归 URL 解码直到结果不变，返回每一层的解码结果（用于多层编码检测）"""
    layers = [path]
    current = path
    for _ in range(max_depth):
        decoded = urllib.parse.unquote(current)
        if decoded == current:
            break
        layers.append(decoded)
        current = decoded
    return layers


@images_bp.route('/<path:path>')
def catch_all(path):
    """捕获所有路由，SPA 回退"""

    if path.startswith('api/') or path.startswith('image/') or path.startswith('upload'):
        return jsonify({'success': False, 'error': 'Not found'}), 404

    # 安全检查：递归解码各层，拒绝任何包含 .. 或绝对路径的请求
    # 防御 %2e%2e、%252e%252e 等多层 URL 编码绕过
    decoded_layers = _decode_recursive(path)
    for layer in decoded_layers:
        normalized = os.path.normpath(layer)
        if '..' in normalized:
            return jsonify({'success': False, 'error': 'Invalid path'}), 400
        if normalized.startswith('/') or normalized.startswith('\\\\'):
            return jsonify({'success': False, 'error': 'Invalid path'}), 400

    try:
        # 使用 Path.resolve() + is_relative_to() 作为最终防线
        static_path = Path(STATIC_FOLDER).resolve()
        target = (static_path / path).resolve()

        if not target.is_relative_to(static_path):
            return jsonify({'success': False, 'error': 'Invalid path'}), 400

        if target.is_file():
            return send_from_directory(STATIC_FOLDER, path)

        if target.is_dir():
            index_in_dir = target / 'index.html'
            if index_in_dir.is_file():
                return send_from_directory(STATIC_FOLDER, f"{path}/index.html")

    except (ValueError, OSError):
        pass

    # SPA 回退
    fallback = Path(STATIC_FOLDER) / '200.html'
    if fallback.is_file():
        return send_from_directory(STATIC_FOLDER, '200.html')

    index = Path(STATIC_FOLDER) / 'index.html'
    if index.is_file():
        return send_from_directory(STATIC_FOLDER, 'index.html')

    return jsonify({'success': False, 'error': 'Not found'}), 404
