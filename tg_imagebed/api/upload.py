#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上传路由模块 - 处理文件上传 API
"""
from __future__ import annotations

import os
import tempfile
import time
from flask import request, jsonify

from . import upload_bp
from ..config import logger
from ..utils import add_cache_headers, format_size, get_image_domain, get_client_ip
from ..services.file_service import process_upload
from ..database import is_guest_upload_allowed, get_system_setting_int
from ..rate_limiter import check_daily_upload_limit

# 图片魔数签名
IMAGE_SIGNATURES = {
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'\xff\xd8\xff': 'image/jpeg',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',       # WebP (需额外检查 WEBP 标识)
    b'BM': 'image/bmp',
    b'\x49\x49\x2A\x00': 'image/tiff',  # TIFF Little-Endian
    b'\x4D\x4D\x00\x2A': 'image/tiff',  # TIFF Big-Endian
    b'\x00\x00\x01\x00': 'image/x-icon', # ICO
}

# 魔数 MIME → 扩展名映射（用于无扩展名文件的深度校验）
_MIME_TO_EXTENSION = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/bmp': 'bmp',
    'image/tiff': 'tif',
    'image/x-icon': 'ico',
    'image/avif': 'avif',
}


def validate_image_magic(content: bytes) -> str | None:
    """基于魔数验证图片类型，返回 MIME 类型或 None"""
    if len(content) < 12:
        return None
    for sig, mime in IMAGE_SIGNATURES.items():
        if content.startswith(sig):
            if sig == b'RIFF' and content[8:12] != b'WEBP':
                continue
            return mime
    # AVIF 特殊检测：ISOBMFF 容器，偏移 4 字节处为 'ftyp'，
    # 然后在 8-32 字节范围内包含 'avif' 或 'avis' 品牌标识
    if len(content) >= 12 and content[4:8] == b'ftyp':
        brand_region = content[8:min(32, len(content))]
        if b'avif' in brand_region or b'avis' in brand_region:
            return 'image/avif'
    return None


def is_extension_allowed(filename: str) -> bool:
    """检查文件扩展名是否在允许列表中"""
    from ..settings_manager import settings_manager
    if not filename:
        return True  # 无文件名时跳过扩展名检查，依赖魔数校验
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if not ext:
        return True  # 无扩展名时跳过，依赖魔数校验
    return ext in settings_manager.get_allowed_extensions()


def validate_upload_file(file) -> tuple:
    """
    公共文件上传校验（扩展名、Content-Type、大小、魔数）
    返回 (error_response, temp_file_path) — error_response 为 None 表示校验通过
    文件被流式保存到临时文件，校验通过时返回临时文件路径（调用方负责清理）
    """
    content_type = (file.content_type or '').strip().lower()

    # 检查文件扩展名是否在允许列表中（SVG 等危险格式由白名单统一控制）
    if not is_extension_allowed(file.filename):
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in (file.filename or '') else ''
        return (add_cache_headers(jsonify({'success': False, 'error': f'不支持的文件格式: .{ext}'}), 'no-cache'), 400), None

    # 初步检查 Content-Type
    if content_type and not content_type.startswith('image/'):
        return (add_cache_headers(jsonify({'success': False, 'error': '只允许上传图片文件'}), 'no-cache'), 400), None

    # 检查文件大小（使用动态配置）
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    max_size_mb = get_system_setting_int('max_file_size_mb', 100, minimum=1, maximum=1024)
    max_size_bytes = max_size_mb * 1024 * 1024

    if file_size > max_size_bytes:
        return (add_cache_headers(jsonify({'success': False, 'error': f'文件大小超过 {max_size_mb}MB 限制'}), 'no-cache'), 400), None

    # 拒绝 0 字节文件（先于魔数校验，避免极小内容绕过）
    if file_size == 0:
        return (add_cache_headers(jsonify({'success': False, 'error': '不允许上传空文件'}), 'no-cache'), 400), None

    # 只读前 32 字节校验魔数（不加载完整文件到内存）
    header = file.read(32)
    file.seek(0)  # 复位，供后续 stream save 使用

    detected_mime = validate_image_magic(header)
    if not detected_mime:
        return (add_cache_headers(jsonify({'success': False, 'error': '无效的图片文件格式'}), 'no-cache'), 400), None

    # 对无扩展名文件，用魔数反查扩展名是否在允许列表（防御绕过）
    if not file.filename or '.' not in (file.filename or ''):
        from ..settings_manager import settings_manager
        detected_ext = _MIME_TO_EXTENSION.get(detected_mime, '')
        if detected_ext and detected_ext not in settings_manager.get_allowed_extensions():
            return (add_cache_headers(jsonify(
                {'success': False, 'error': f'不支持的文件格式: .{detected_ext}'}), 'no-cache'), 400), None

    # 流式保存到临时文件（避免大文件 OOM）
    fd, temp_path = tempfile.mkstemp(suffix='.tmp', prefix='upload_')
    os.close(fd)
    file.save(temp_path)

    return None, temp_path


@upload_bp.route('/api/upload', methods=['POST'])
@upload_bp.route('/upload', methods=['POST'])
def upload_file():
    """处理前端文件上传（匿名上传）"""
    # 检查游客上传权限
    if not is_guest_upload_allowed():
        return add_cache_headers(jsonify({
            'success': False,
            'error': '匿名上传已关闭，请使用 Token 上传或联系管理员'
        }), 'no-cache'), 403

    # 检查文件
    if 'file' not in request.files:
        return add_cache_headers(jsonify({'success': False, 'error': 'No file provided'}), 'no-cache'), 400

    file = request.files['file']
    if file.filename == '':
        return add_cache_headers(jsonify({'success': False, 'error': 'No file selected'}), 'no-cache'), 400

    # 检查每日上传限制（按客户端 IP 独立限额）
    daily_limit = get_system_setting_int('daily_upload_limit', 0, minimum=0, maximum=1000000)
    if daily_limit > 0:
        client_ip = get_client_ip(request)
        if not check_daily_upload_limit(client_ip, daily_limit):
            return add_cache_headers(jsonify(
                {'success': False, 'error': f'该 IP 已达到每日上传限制({daily_limit}张)，请明天再试'}
            ), 'no-cache'), 429

    # 公共文件校验（扩展名、Content-Type、大小、魔数）— 返回临时文件路径
    err, temp_path = validate_upload_file(file)
    if err:
        return err

    try:
        # 处理上传（通过 file_path 传递，避免全量加载到内存）
        result = process_upload(
            file_path=temp_path,
            filename=file.filename,
            content_type=file.content_type,
            username='web_user',
            source='web_upload'
        )

        if not result:
            return add_cache_headers(jsonify({'success': False, 'error': 'Failed to upload to Telegram'}), 'no-cache'), 500

        # 生成 URL
        base_url = get_image_domain(request, scene='guest')
        permanent_url = f"{base_url}/view/{result['encrypted_id']}"

        logger.info(f"Web上传完成: {file.filename} -> {result['encrypted_id']}")

        return add_cache_headers(jsonify({
            'success': True,
            'data': {
                'url': permanent_url,
                'filename': file.filename,
                'size': format_size(result['file_size']),
                'upload_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }
        }), 'no-cache')

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return add_cache_headers(jsonify({'success': False, 'error': '上传失败，请稍后重试'}), 'no-cache'), 500
    finally:
        # 清理临时文件
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
