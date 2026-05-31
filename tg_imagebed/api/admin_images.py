#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员路由 - 图片管理（统计、列表、删除）

从 admin_module.register_admin_routes 迁移出来。
"""
import sqlite3
from datetime import datetime, timedelta

from flask import request, jsonify

from . import admin_bp
from .admin_helpers import _admin_options
from ..config import logger
from ..utils import add_cache_headers, format_size, get_image_domain
from ..database.connection import get_connection
from .. import admin_module


def _parse_query_date(value: str, day_end: bool = False):
    """解析日期过滤参数"""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, '%Y-%m-%d')
        if day_end:
            dt = dt + timedelta(days=1) - timedelta(seconds=1)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        logger.debug(f"无效日期参数: {raw}")
        return None


# ============ 统计 ============

@admin_bp.route('/api/admin/stats', methods=['GET', 'OPTIONS'])
@admin_module.login_required
def admin_stats():
    """获取管理统计信息"""
    from ..database import get_system_setting, get_stats as _get_db_stats

    if request.method == 'OPTIONS':
        return _admin_options('GET, OPTIONS')

    try:
        db_stats = _get_db_stats()
        total_files = db_stats.get('total_files', 0)
        total_size = db_stats.get('total_size', 0)

        # 获取今日上传数
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                today_start_ts = int(today_start.timestamp())
                today_end_ts = int(today_end.timestamp())

                cursor.execute(
                    "SELECT COUNT(*) FROM file_storage WHERE upload_time >= ? AND upload_time <= ?",
                    (today_start_ts, today_end_ts)
                )
                today_uploads = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM file_storage WHERE cdn_cached = 1")
                cdn_cached = cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"查询统计数据失败: {e}")
                today_uploads = 0
                cdn_cached = 0

        # 读取配置状态
        cdn_enabled = str(get_system_setting('cdn_enabled') or '0') == '1'
        cdn_monitor_enabled = str(get_system_setting('cdn_monitor_enabled') or '0') == '1'
        cdn_domain = str(get_system_setting('cloudflare_cdn_domain') or '').strip()
        group_upload_admin_only = str(get_system_setting('group_upload_admin_only') or '0') == '1'
        cdn_monitor_display = '已启用' if (cdn_enabled and cdn_monitor_enabled) else '已关闭'

        response_data = {
            'success': True,
            'data': {
                'stats': {
                    'totalImages': total_files,
                    'totalSize': format_size(total_size),
                    'todayUploads': today_uploads,
                    'cdnCached': cdn_cached
                },
                'config': {
                    'cdnStatus': '已启用' if cdn_enabled else '未启用',
                    'cdnDomain': cdn_domain if cdn_domain else '未配置',
                    'uptime': '运行中',
                    'groupUpload': '仅管理员' if group_upload_admin_only else '已开放',
                    'cdnMonitor': cdn_monitor_display
                }
            }
        }

        logger.debug(f"返回统计数据: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取统计信息失败',
            'message': '服务器内部错误'
        }), 500


# ============ 图片列表 ============

@admin_bp.route('/api/admin/images', methods=['GET', 'OPTIONS'])
@admin_module.login_required
def admin_images():
    """获取图片列表（支持分页、搜索和筛选）"""
    from ..database import get_system_setting

    if request.method == 'OPTIONS':
        return _admin_options('GET, OPTIONS')

    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        search = request.args.get('search', '').strip()
        filter_type = request.args.get('filter', 'all').strip().lower()
        sort_by = request.args.get('sort_by', 'created_at').strip().lower()
        sort_order = request.args.get('sort_order', 'desc').strip().lower()
        source = request.args.get('source', '').strip().lower()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        size_min = request.args.get('size_min', type=float)
        size_max = request.args.get('size_max', type=float)
        access_min = request.args.get('access_min', type=float)
        access_max = request.args.get('access_max', type=float)

        page = max(1, page)
        limit = max(1, min(200, limit))

        if filter_type not in ('all', 'cached', 'uncached', 'group'):
            filter_type = 'all'

        sort_by_map = {
            'created_at': 'fs.created_at',
            'file_size': 'fs.file_size',
            'access_count': 'fs.access_count',
            'cdn_hit_count': 'fs.cdn_hit_count',
            'direct_hit_count': 'fs.direct_hit_count',
        }
        if sort_by not in sort_by_map:
            sort_by = 'created_at'

        if sort_order not in ('asc', 'desc'):
            sort_order = 'desc'

        if source == 'all':
            source = ''

        date_from_dt = _parse_query_date(date_from, day_end=False)
        date_to_dt = _parse_query_date(date_to, day_end=True)

        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA table_info(file_storage)")
            columns = [column[1] for column in cursor.fetchall()]

            offset = (page - 1) * limit

            select_columns = [
                'fs.encrypted_id', 'fs.file_id', 'fs.original_filename',
                'fs.file_size', 'fs.source', 'fs.created_at', 'fs.username',
                'fs.access_count', 'fs.last_accessed', 'fs.upload_time',
                'fs.cdn_cached', 'fs.cdn_cache_time', 'fs.mime_type'
            ]

            if 'is_group_upload' in columns:
                select_columns.append('fs.is_group_upload')
            if 'cdn_hit_count' in columns:
                select_columns.append('fs.cdn_hit_count')
            if 'direct_hit_count' in columns:
                select_columns.append('fs.direct_hit_count')

            query = f"SELECT {', '.join(select_columns)} FROM file_storage fs"

            where_clauses = []
            where_params = []

            if search:
                where_clauses.append('(fs.original_filename LIKE ? OR fs.username LIKE ?)')
                search_pattern = f'%{search}%'
                where_params.extend([search_pattern, search_pattern])

            if filter_type == 'cached':
                if 'cdn_cached' in columns:
                    where_clauses.append('fs.cdn_cached = 1')
                else:
                    where_clauses.append('1 = 0')
            elif filter_type == 'uncached':
                if 'cdn_cached' in columns:
                    where_clauses.append('(fs.cdn_cached = 0 OR fs.cdn_cached IS NULL)')
            elif filter_type == 'group':
                if 'is_group_upload' in columns:
                    where_clauses.append('fs.is_group_upload = 1')
                else:
                    where_clauses.append('1 = 0')

            if source:
                if source == 'group':
                    if 'is_group_upload' in columns:
                        where_clauses.append('fs.is_group_upload = 1')
                    else:
                        where_clauses.append('fs.source = ?')
                        where_params.append('group')
                elif source == 'token':
                    where_clauses.append('fs.source LIKE ?')
                    where_params.append('%token%')
                elif source == 'guest':
                    where_clauses.append(
                        '(fs.source = ? OR fs.source = ? OR fs.source = ? OR fs.source LIKE ?)'
                    )
                    where_params.extend(['guest', 'anonymous', 'web', 'guest_%'])
                else:
                    where_clauses.append('fs.source = ?')
                    where_params.append(source)

            if date_from_dt:
                where_clauses.append('datetime(fs.created_at) >= datetime(?)')
                where_params.append(date_from_dt)
            if date_to_dt:
                where_clauses.append('datetime(fs.created_at) <= datetime(?)')
                where_params.append(date_to_dt)

            if size_min is not None and size_min >= 0:
                where_clauses.append('fs.file_size >= ?')
                where_params.append(int(size_min))
            if size_max is not None and size_max >= 0:
                where_clauses.append('fs.file_size <= ?')
                where_params.append(int(size_max))

            if access_min is not None and access_min >= 0:
                where_clauses.append('COALESCE(fs.access_count, 0) >= ?')
                where_params.append(int(access_min))
            if access_max is not None and access_max >= 0:
                where_clauses.append('COALESCE(fs.access_count, 0) <= ?')
                where_params.append(int(access_max))

            if where_clauses:
                query += ' WHERE ' + ' AND '.join(where_clauses)

            count_query = 'SELECT COUNT(*) FROM file_storage fs'
            if where_clauses:
                count_query += ' WHERE ' + ' AND '.join(where_clauses)
            cursor.execute(count_query, where_params)
            total_count = cursor.fetchone()[0]

            sort_column = sort_by_map.get(sort_by, 'fs.created_at')
            if sort_by == 'cdn_hit_count' and 'cdn_hit_count' not in columns:
                sort_column = 'fs.access_count'
            if sort_by == 'direct_hit_count' and 'direct_hit_count' not in columns:
                sort_column = 'fs.access_count'

            query += f' ORDER BY {sort_column} {sort_order.upper()} LIMIT ? OFFSET ?'
            params = list(where_params)
            params.extend([limit, offset])

            cursor.execute(query, params)
            images = []

            for row in cursor.fetchall():
                image_data = dict(row)

                if 'is_group_upload' not in image_data:
                    image_data['is_group_upload'] = 0
                if 'cdn_hit_count' not in image_data:
                    image_data['cdn_hit_count'] = 0
                if 'direct_hit_count' not in image_data:
                    image_data['direct_hit_count'] = 0

                if image_data.get('upload_time'):
                    try:
                        timestamp = int(image_data['upload_time'])
                        dt = datetime.fromtimestamp(timestamp)
                        image_data['created_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        pass

                if 'created_at' in image_data and image_data['created_at'] \
                        and not isinstance(image_data['created_at'], str):
                    created_at = image_data['created_at']
                    try:
                        if isinstance(created_at, (int, float)):
                            dt = datetime.fromtimestamp(created_at)
                            image_data['created_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            created_at_str = str(created_at)
                            if 'T' in created_at_str:
                                dt = datetime.fromisoformat(
                                    created_at_str.replace('Z', '+00:00')
                                )
                                image_data['created_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                            elif ' ' in created_at_str:
                                image_data['created_at'] = created_at_str
                            else:
                                dt = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
                                image_data['created_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        image_data['created_at'] = str(created_at) if created_at else '未知时间'

                if image_data.get('last_accessed'):
                    try:
                        last_accessed = image_data['last_accessed']
                        if isinstance(last_accessed, str) and 'T' in last_accessed:
                            dt = datetime.fromisoformat(last_accessed.replace('Z', '+00:00'))
                            image_data['last_accessed'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        elif isinstance(last_accessed, (int, float)):
                            dt = datetime.fromtimestamp(last_accessed)
                            image_data['last_accessed'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            image_data['last_accessed'] = str(last_accessed)
                    except Exception:
                        image_data['last_accessed'] = None

                if image_data.get('cdn_cache_time'):
                    try:
                        cdn_cache_time = image_data['cdn_cache_time']
                        if isinstance(cdn_cache_time, str) and 'T' in cdn_cache_time:
                            dt = datetime.fromisoformat(cdn_cache_time.replace('Z', '+00:00'))
                            image_data['cdn_cache_time'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        elif isinstance(cdn_cache_time, (int, float)):
                            dt = datetime.fromtimestamp(cdn_cache_time)
                            image_data['cdn_cache_time'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            image_data['cdn_cache_time'] = str(cdn_cache_time)
                    except Exception:
                        image_data['cdn_cache_time'] = None

                if 'created_at' not in image_data or not image_data['created_at']:
                    image_data['created_at'] = '未知时间'
                elif not isinstance(image_data['created_at'], str):
                    image_data['created_at'] = str(image_data['created_at'])

                images.append(image_data)

        total_pages = (total_count + limit - 1) // limit

        base_url = get_image_domain(request).rstrip('/')

        cdn_domain = ''
        cdn_enabled = False
        try:
            cdn_enabled = str(get_system_setting('cdn_enabled') or '0') == '1'
            cdn_domain = str(get_system_setting('cloudflare_cdn_domain') or '').strip()
        except Exception as e:
            logger.debug(f"读取 CDN 域名配置失败: {e}")

        for img in images:
            img['url'] = f"{base_url}/image/{img['encrypted_id']}"
            img['share_url'] = f"{base_url}/view/{img['encrypted_id']}"
            if cdn_enabled and cdn_domain:
                img['cdn_url'] = f"https://{cdn_domain}/image/{img['encrypted_id']}"
            else:
                img['cdn_url'] = None
            img['id'] = img['encrypted_id']
            img['filename'] = img.get('original_filename', '未知文件')
            img['size'] = img.get('file_size', 0)
            img['uploadTime'] = img.get('created_at', '未知时间')
            img['cached'] = bool(img.get('cdn_cached', 0))

        response_data = {
            'success': True,
            'data': {
                'images': images,
                'totalPages': total_pages,
                'total': total_count,
                'page': page,
                'limit': limit
            }
        }

        logger.info(f"成功返回图片列表: {len(images)} 张图片, 总页数: {total_pages}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"获取图片列表失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '获取图片列表失败',
            'message': '服务器内部错误'
        }), 500


# ============ 删除图片 ============

def _chunked(seq, size=900):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


@admin_bp.route('/api/admin/delete', methods=['POST', 'OPTIONS'])
@admin_module.login_required
def admin_delete_images():
    """删除图片，支持同步删除存储后端文件和TG群组消息"""
    import requests as _requests
    import json as _json

    if request.method == 'OPTIONS':
        return _admin_options('POST, OPTIONS')

    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    delete_storage = data.get('delete_storage', True)

    if not isinstance(ids, list) or not ids:
        return jsonify({'success': False, 'message': '没有选择要删除的图片'}), 400

    ids = [str(x).strip() for x in ids if x is not None and str(x).strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return jsonify({'success': False, 'message': '没有选择要删除的图片'}), 400

    deleted_count = 0
    deleted_size = 0
    tg_deleted_count = 0
    storage_deleted_count = 0

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA table_info(file_storage)")
            db_columns = [col[1] for col in cursor.fetchall()]
            has_group_cols = 'group_chat_id' in db_columns

            files_to_delete = []
            for chunk in _chunked(ids):
                placeholders = ','.join('?' * len(chunk))
                try:
                    if has_group_cols:
                        sql = (
                            "SELECT encrypted_id, file_size, group_chat_id, "
                            "group_message_id, storage_backend, storage_meta, storage_key "
                            f"FROM file_storage WHERE encrypted_id IN ({placeholders})"
                        )
                    else:
                        sql = (
                            "SELECT encrypted_id, file_size, NULL, NULL, NULL, NULL, NULL "
                            f"FROM file_storage WHERE encrypted_id IN ({placeholders})"
                        )
                    cursor.execute(sql, chunk)
                except sqlite3.OperationalError as e:
                    if 'no such column' in str(e).lower():
                        sql = (
                            "SELECT encrypted_id, file_size, NULL, NULL, NULL, NULL, NULL "
                            f"FROM file_storage WHERE encrypted_id IN ({placeholders})"
                        )
                        cursor.execute(sql, chunk)
                    else:
                        raise
                files_to_delete.extend(cursor.fetchall())

            for row in files_to_delete:
                if row[1]:
                    deleted_size += row[1]

            tg_sync_delete_enabled = True
            try:
                from ..database import get_system_setting
                tg_sync_delete_enabled = (
                    str(get_system_setting('tg_sync_delete_enabled') or '1') == '1'
                )
            except Exception:
                pass

            if delete_storage and tg_sync_delete_enabled:
                try:
                    from ..storage.router import get_storage_router
                    router = get_storage_router()
                    for row in files_to_delete:
                        encrypted_id = row[0]
                        storage_backend_name = row[4] if len(row) > 4 else None
                        storage_key = row[6] if len(row) > 6 else None
                        if storage_key and storage_backend_name:
                            try:
                                backend = router.get_backend(storage_backend_name.strip())
                                backend.delete(storage_key=storage_key)
                                storage_deleted_count += 1
                            except Exception as e:
                                logger.debug(f"删除存储文件失败: {encrypted_id}, {e}")
                except Exception as e:
                    logger.debug(f"存储后端删除跳过: {e}")

            if delete_storage and tg_sync_delete_enabled:
                try:
                    from ..bot_control import get_effective_bot_token
                    bot_token, _ = get_effective_bot_token()
                    if bot_token:
                        try:
                            from ..storage.router import get_storage_router
                            _router = get_storage_router()
                        except Exception:
                            _router = None

                        seen = set()
                        for row in files_to_delete:
                            chat_id, message_id = row[2], row[3]
                            storage_backend_name = row[4] if len(row) > 4 else None
                            storage_meta_raw = row[5] if len(row) > 5 else None

                            if message_id is None or chat_id is None:
                                try:
                                    meta = _json.loads(storage_meta_raw) \
                                        if isinstance(storage_meta_raw, str) and storage_meta_raw \
                                        else {}
                                    if message_id is None:
                                        message_id = meta.get('message_id')
                                    if chat_id is None and storage_backend_name and _router:
                                        try:
                                            be = _router.get_backend(
                                                storage_backend_name.strip()
                                            )
                                            if hasattr(be, '_chat_id'):
                                                chat_id = be._chat_id
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                            if chat_id is None or message_id is None:
                                continue
                            key = (chat_id, message_id)
                            if key in seen:
                                continue
                            seen.add(key)
                            try:
                                url = (
                                    f"https://api.telegram.org/bot{bot_token}"
                                    f"/deleteMessage"
                                )
                                resp = _requests.post(url, data={
                                    'chat_id': chat_id,
                                    'message_id': message_id
                                }, timeout=5)
                                if resp.ok:
                                    try:
                                        payload = resp.json()
                                        if payload.get('ok') is True:
                                            tg_deleted_count += 1
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"TG消息删除跳过: {e}")

            for chunk in _chunked(ids):
                placeholders = ','.join('?' * len(chunk))
                cursor.execute(
                    f"DELETE FROM file_storage WHERE encrypted_id IN ({placeholders})",
                    chunk
                )
                deleted_count += cursor.rowcount

        logger.info(
            f"管理员删除了 {deleted_count} 张图片，"
            f"TG消息同步删除 {tg_deleted_count} 条，"
            f"存储文件删除 {storage_deleted_count} 个"
        )

        return jsonify({
            'success': True,
            'data': {
                'deleted': deleted_count,
                'tg_deleted': tg_deleted_count,
                'storage_deleted': storage_deleted_count,
                'message': f'成功删除 {deleted_count} 张图片'
            }
        })

    except Exception as e:
        logger.error(f"删除图片失败: {e}")
        return jsonify({'success': False, 'message': '删除失败'}), 500
