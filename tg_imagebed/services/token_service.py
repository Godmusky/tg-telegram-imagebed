#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 统一调度层 — 级联删除 / 影响范围查询 / 批量操作
"""
from typing import Any, Dict, List, Optional

from ..config import logger
from ..database import (
    admin_create_token,
    admin_delete_token,
    get_system_setting,
)
from ..database.connection import get_connection


class TokenService:
    """Token 管理统一入口，封装级联清理与批量操作逻辑。"""

    # ── 创建 ──────────────────────────────────────────────
    @staticmethod
    def create_token(
        *,
        description: Optional[str] = None,
        expires_at: Any = None,
        upload_limit: int = 100,
        is_active: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """统一创建 Token，委托给 database 层。"""
        return admin_create_token(
            description=description,
            expires_at=expires_at,
            upload_limit=upload_limit,
            is_active=is_active,
        )

    # ── Phase 1: DB-only 删除（事务内执行） ─────────────────
    @staticmethod
    def _delete_images_for_token_str(token_str: str, cursor) -> Dict[str, Any]:
        """
        Phase 1（DB 事务内执行）：查询图片 → 批量 DELETE → 更新计数。
        仅收集待清理任务，不执行任何 HTTP 或存储 I/O 操作。

        Returns:
            {
                "images_deleted": int,
                "pending": [
                    {"type": "storage_file", "storage_key": ..., "storage_backend": ...},
                    {"type": "tg_message", "chat_id": ..., "message_id": ...},
                ],
                "bot_token": str | None,
            }
        """
        from ..storage.router import get_storage_router

        result: Dict[str, Any] = {"images_deleted": 0, "pending": [], "bot_token": None}

        cursor.execute(
            "SELECT encrypted_id, storage_backend, storage_key, "
            "group_chat_id, group_message_id, storage_meta "
            "FROM file_storage WHERE auth_token = ?",
            (token_str,),
        )
        files = cursor.fetchall()
        if not files:
            return result

        # 检查 TG 同步删除设置 + 获取 bot_token
        tg_sync_delete_enabled = (
            str(get_system_setting("tg_sync_delete_enabled") or "1") == "1"
        )
        bot_token = None
        if tg_sync_delete_enabled:
            try:
                from ..bot_control import get_effective_bot_token

                bot_token, _ = get_effective_bot_token()
            except Exception:
                pass
        result["bot_token"] = bot_token

        router = get_storage_router()
        tg_seen: set = set()
        encrypted_ids: list = []

        for row in files:
            file_row = dict(row)
            encrypted_id = file_row["encrypted_id"]
            storage_backend = (file_row.get("storage_backend") or "telegram").strip()
            storage_key = file_row.get("storage_key") or ""

            encrypted_ids.append(encrypted_id)

            # 收集存储文件删除任务
            if storage_key:
                result["pending"].append(
                    {
                        "type": "storage_file",
                        "storage_key": storage_key,
                        "storage_backend": storage_backend,
                    }
                )

            # 收集 TG 消息删除任务
            if bot_token:
                chat_id = file_row.get("group_chat_id")
                message_id = file_row.get("group_message_id")

                # 兼容历史数据：从 storage_meta / 后端配置提取
                if not message_id or not chat_id:
                    try:
                        import json as _json

                        meta_raw = file_row.get("storage_meta") or "{}"
                        meta = (
                            _json.loads(meta_raw)
                            if isinstance(meta_raw, str)
                            else (meta_raw or {})
                        )
                        if not message_id:
                            message_id = meta.get("message_id")
                        if not chat_id and storage_backend:
                            try:
                                be = router.get_backend(storage_backend)
                                if hasattr(be, "_chat_id"):
                                    chat_id = be._chat_id
                            except Exception:
                                pass
                    except Exception:
                        pass

                if chat_id and message_id:
                    key = (chat_id, message_id)
                    if key not in tg_seen:
                        tg_seen.add(key)
                        result["pending"].append(
                            {
                                "type": "tg_message",
                                "chat_id": chat_id,
                                "message_id": message_id,
                            }
                        )

        # 批量删除数据库记录（分块处理）
        def _chunked(seq, size=900):
            for i in range(0, len(seq), size):
                yield seq[i : i + size]

        for chunk in _chunked(encrypted_ids):
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(
                f"DELETE FROM file_storage WHERE encrypted_id IN ({placeholders})",
                chunk,
            )
            result["images_deleted"] += cursor.rowcount

        # 递减 token 的 upload_count（不低于 0）
        if result["images_deleted"] > 0:
            cursor.execute(
                "UPDATE auth_tokens SET upload_count = MAX(0, upload_count - ?) WHERE token = ?",
                (result["images_deleted"], token_str),
            )

        return result

    # ── Phase 2: 事务提交后清理 ─────────────────────────────
    @staticmethod
    def _execute_pending_cleanup(
        pending: List[dict], bot_token: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Phase 2（事务提交后执行）：异步清理存储文件和 TG 消息。
        每条任务独立 try/except，单条失败不影响其他。

        Returns: {"tg_deleted": int, "storage_deleted": int}
        """
        import requests as http_requests

        result = {"tg_deleted": 0, "storage_deleted": 0}

        if not pending:
            return result

        # 延迟加载存储路由器（避免在事务内 import）
        _router = None

        for entry in pending:
            entry_type = entry.get("type", "")

            if entry_type == "storage_file":
                try:
                    if _router is None:
                        from ..storage.router import get_storage_router

                        _router = get_storage_router()
                    backend = _router.get_backend(
                        entry.get("storage_backend", "telegram")
                    )
                    backend.delete(storage_key=entry["storage_key"])
                    result["storage_deleted"] += 1
                except Exception as e:
                    logger.debug(
                        f"Post-commit storage delete failed: {entry.get('storage_key')}, {e}"
                    )

            elif entry_type == "tg_message" and bot_token:
                try:
                    resp = http_requests.post(
                        f"https://api.telegram.org/bot{bot_token}/deleteMessage",
                        data={
                            "chat_id": entry["chat_id"],
                            "message_id": entry["message_id"],
                        },
                        timeout=5,
                    )
                    if resp.ok and resp.json().get("ok"):
                        result["tg_deleted"] += 1
                except Exception as e:
                    logger.debug(f"Post-commit TG delete failed: {entry}, {e}")

        return result

    # ── 级联删除 ──────────────────────────────────────────
    @staticmethod
    def delete_token(token_id: int, *, delete_images: bool = False) -> bool:
        """
        级联删除 Token：
        1. （可选）Phase 1: 事务内删除关联图片（DB 记录）
        2. file_storage.auth_token 置空（仅在不删除图片时）
        3. galleries.owner_token 置空（owner_type='token' 的画集）
        4. gallery_token_access 清理
        5. 删除 auth_tokens 记录
        6. Phase 2: 事务提交后异步删除存储文件 + TG 消息
        """
        pending_cleanup: list = []
        bot_token: Optional[str] = None

        try:
            with get_connection() as conn:
                cursor = conn.cursor()

                # 先查出 token 字符串
                cursor.execute(
                    "SELECT token FROM auth_tokens WHERE rowid = ?",
                    (int(token_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                token_str = row[0]

                # 可选：删除关联图片（仅 DB 操作，事务内）
                if delete_images:
                    result = TokenService._delete_images_for_token_str(
                        token_str, cursor
                    )
                    pending_cleanup = result.get("pending", [])
                    bot_token = result.get("bot_token")
                else:
                    # 仅置空 auth_token
                    cursor.execute(
                        "UPDATE file_storage SET auth_token = NULL WHERE auth_token = ?",
                        (token_str,),
                    )

                # galleries.owner_token 置空
                cursor.execute(
                    "UPDATE galleries SET owner_token = NULL WHERE owner_token = ?",
                    (token_str,),
                )
                # gallery_token_access 清理
                cursor.execute(
                    "DELETE FROM gallery_token_access WHERE token = ?",
                    (token_str,),
                )
                # 删除 auth_tokens
                cursor.execute(
                    "DELETE FROM auth_tokens WHERE rowid = ?",
                    (int(token_id),),
                )

            # Phase 2: 事务已提交，异步清理存储文件 + TG 消息
            if pending_cleanup:
                TokenService._execute_pending_cleanup(pending_cleanup, bot_token)

            action = "级联删除（含图片）" if delete_images else "级联删除"
            logger.info(f"TokenService {action} Token: ID={token_id}")
            return True

        except Exception as e:
            logger.error(f"TokenService 级联删除 Token 失败: {e}")
            raise

    # ── 影响范围查询 ──────────────────────────────────────
    @staticmethod
    def get_token_impact(token_id: int) -> Optional[Dict[str, Any]]:
        """查询删除该 Token 的影响范围。返回 None 表示 Token 不存在。"""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT token FROM auth_tokens WHERE rowid = ?",
                    (int(token_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                token_str = row[0]

                cursor.execute(
                    "SELECT COUNT(1) FROM file_storage WHERE auth_token = ?",
                    (token_str,),
                )
                upload_count = cursor.fetchone()[0] or 0

                cursor.execute(
                    "SELECT COUNT(1) FROM galleries WHERE owner_token = ?",
                    (token_str,),
                )
                gallery_count = cursor.fetchone()[0] or 0

                cursor.execute(
                    "SELECT COUNT(1) FROM gallery_token_access WHERE token = ?",
                    (token_str,),
                )
                access_count = cursor.fetchone()[0] or 0

            return {
                "upload_count": upload_count,
                "gallery_count": gallery_count,
                "access_count": access_count,
            }

        except Exception as e:
            logger.error(f"TokenService 查询影响范围失败: {e}")
            raise

    # ── 批量操作 ──────────────────────────────────────────
    @staticmethod
    def batch_update_status(token_ids: List[int], is_active: bool) -> Dict[str, int]:
        """批量启用/禁用，返回 {success_count, fail_count}。"""
        success = 0
        fail = 0
        active_val = 1 if is_active else 0
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                for tid in token_ids:
                    try:
                        cursor.execute(
                            "UPDATE auth_tokens SET is_active = ? WHERE rowid = ?",
                            (active_val, int(tid)),
                        )
                        if cursor.rowcount > 0:
                            success += 1
                        else:
                            fail += 1
                    except Exception:
                        fail += 1
        except Exception as e:
            logger.error(f"TokenService 批量更新状态失败: {e}")
            raise
        status_text = "启用" if is_active else "禁用"
        logger.info(f"TokenService 批量{status_text}: 成功={success}, 失败={fail}")
        return {"success_count": success, "fail_count": fail}

    @staticmethod
    def batch_delete(
        token_ids: List[int], *, delete_images: bool = False
    ) -> Dict[str, int]:
        """
        批量级联删除，返回 {success_count, fail_count, images_deleted, tg_deleted}。

        Phase 1（事务内）：对每个 token 执行 DB 删除 + 收集待清理任务。
        Phase 2（事务提交后）：统一异步清理存储文件 + TG 消息。
        """
        success = 0
        fail = 0
        total_images_deleted = 0
        total_tg_deleted = 0
        all_pending: list = []
        all_bot_token: Optional[str] = None

        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                for tid in token_ids:
                    try:
                        cursor.execute(
                            "SELECT token FROM auth_tokens WHERE rowid = ?",
                            (int(tid),),
                        )
                        row = cursor.fetchone()
                        if not row:
                            fail += 1
                            continue
                        token_str = row[0]

                        # 可选：删除关联图片（仅 DB 操作，事务内）
                        if delete_images:
                            img_result = TokenService._delete_images_for_token_str(
                                token_str, cursor
                            )
                            total_images_deleted += img_result["images_deleted"]
                            all_pending.extend(img_result.get("pending", []))
                            if img_result.get("bot_token"):
                                all_bot_token = img_result["bot_token"]
                        else:
                            cursor.execute(
                                "UPDATE file_storage SET auth_token = NULL WHERE auth_token = ?",
                                (token_str,),
                            )

                        cursor.execute(
                            "UPDATE galleries SET owner_token = NULL WHERE owner_token = ?",
                            (token_str,),
                        )
                        cursor.execute(
                            "DELETE FROM gallery_token_access WHERE token = ?",
                            (token_str,),
                        )
                        cursor.execute(
                            "DELETE FROM auth_tokens WHERE rowid = ?",
                            (int(tid),),
                        )
                        success += 1
                    except Exception:
                        fail += 1

            # Phase 2: 事务已提交，统一异步清理
            if all_pending:
                cleanup_result = TokenService._execute_pending_cleanup(
                    all_pending, all_bot_token
                )
                total_tg_deleted = cleanup_result.get("tg_deleted", 0)

        except Exception as e:
            logger.error(f"TokenService 批量删除失败: {e}")
            raise

        action = "批量删除（含图片）" if delete_images else "批量删除"
        logger.info(f"TokenService {action}: 成功={success}, 失败={fail}")
        result: Dict[str, int] = {"success_count": success, "fail_count": fail}
        if delete_images:
            result["images_deleted"] = total_images_deleted
            result["tg_deleted"] = total_tg_deleted
        return result

    @staticmethod
    def batch_get_impact(token_ids: List[int]) -> Dict[str, Any]:
        """批量影响范围汇总。"""
        total_uploads = 0
        total_galleries = 0
        total_access = 0
        for tid in token_ids:
            impact = TokenService.get_token_impact(tid)
            if impact:
                total_uploads += impact["upload_count"]
                total_galleries += impact["gallery_count"]
                total_access += impact["access_count"]
        return {
            "token_count": len(token_ids),
            "upload_count": total_uploads,
            "gallery_count": total_galleries,
            "access_count": total_access,
        }

    # ── 用户侧删除（按 token 字符串） ─────────────────────
    @staticmethod
    def delete_token_by_string(
        token: str, *, delete_images: bool = False
    ) -> bool:
        """
        按 token 字符串级联删除（用户侧删除），可选同时删除关联图片。

        Phase 1（事务内）：DB 删除。
        Phase 2（事务提交后）：异步清理存储文件 + TG 消息。
        """
        token = (token or "").strip()
        if not token:
            return False

        pending_cleanup: list = []
        bot_token: Optional[str] = None

        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM auth_tokens WHERE token = ?", (token,)
                )
                if not cursor.fetchone():
                    return False

                # 可选：删除关联图片（仅 DB 操作，事务内）
                if delete_images:
                    result = TokenService._delete_images_for_token_str(token, cursor)
                    pending_cleanup = result.get("pending", [])
                    bot_token = result.get("bot_token")
                else:
                    cursor.execute(
                        "UPDATE file_storage SET auth_token = NULL WHERE auth_token = ?",
                        (token,),
                    )

                cursor.execute(
                    "UPDATE galleries SET owner_token = NULL WHERE owner_token = ?",
                    (token,),
                )
                cursor.execute(
                    "DELETE FROM gallery_token_access WHERE token = ?",
                    (token,),
                )
                cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))

            # Phase 2: 事务已提交，异步清理存储文件 + TG 消息
            if pending_cleanup:
                TokenService._execute_pending_cleanup(pending_cleanup, bot_token)

            action = (
                "用户侧级联删除（含图片）" if delete_images else "用户侧级联删除"
            )
            logger.info(f"{action} Token: {token[:20]}...")
            return True
        except Exception as e:
            logger.error(f"用户侧删除 Token 失败: {e}")
            return False
