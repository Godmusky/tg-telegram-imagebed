#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot 共享辅助函数 — 提供跨模块复用的 Telegram 操作

函数：
- resolve_tg_message_id: 从 file_row 中提取 chat_id / message_id（含历史数据兼容）
- delete_tg_message:     发送单条 deleteMessage API 请求
- batch_delete_tg_messages: 批量删除（去重 + 静默容错）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_tg_message_id(file_row: dict) -> tuple[Optional[str], Optional[int]]:
    """
    从 file_storage 行中提取 Telegram chat_id 和 message_id。

    兼容新格式（group_chat_id / group_message_id 列）和历史数据
    （storage_meta JSON 中存储的 message_id 及 storage backend 的 _chat_id）。

    返回: (chat_id: str | None, message_id: int | None)
    """
    chat_id = file_row.get('group_chat_id')
    message_id = file_row.get('group_message_id')
    storage_backend = (file_row.get('storage_backend') or 'telegram').strip()

    if chat_id and message_id:
        return str(chat_id), int(message_id)

    # ---- 兼容历史数据：从 storage_meta 提取 message_id，从 backend 提取 chat_id ----
    try:
        import json as _json
        meta_raw = file_row.get('storage_meta') or '{}'
        meta = _json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})

        if not message_id:
            message_id = meta.get('message_id')

        if not chat_id:
            try:
                from ..storage.router import get_storage_router
                be = get_storage_router().get_backend(storage_backend)
                if hasattr(be, '_chat_id'):
                    chat_id = be._chat_id
            except Exception:
                pass
    except Exception:
        pass

    if chat_id and message_id:
        return str(chat_id), int(message_id)
    return None, None


def delete_tg_message(chat_id, message_id, bot_token: Optional[str] = None) -> bool:
    """
    通过 Telegram Bot API 删除一条消息。

    bot_token 可选；为 None 时自动从 bot_control 获取。
    返回是否删除成功。
    """
    import requests as http_requests

    if not chat_id or not message_id:
        return False

    if not bot_token:
        try:
            from ..bot_control import get_effective_bot_token
            bot_token, _ = get_effective_bot_token()
        except Exception:
            pass
    if not bot_token:
        return False

    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/deleteMessage",
            data={'chat_id': chat_id, 'message_id': int(message_id)},
            timeout=5,
        )
        return resp.ok and resp.json().get('ok', False)
    except Exception:
        return False


def batch_delete_tg_messages(file_rows: list, bot_token: Optional[str] = None) -> int:
    """
    批量同步删除 Telegram 消息（去重 + 静默容错）。

    遍历 file_rows，解析 chat_id / message_id，去重后逐条调用
    deleteMessage API。静默忽略任何错误。

    bot_token 可选；为 None 时在首次调用时解析一次。

    返回: 成功删除的 TG 消息数。
    """
    if not bot_token:
        try:
            from ..bot_control import get_effective_bot_token
            bot_token, _ = get_effective_bot_token()
        except Exception:
            pass
    if not bot_token:
        return 0

    deleted = 0
    seen = set()
    for row in file_rows:
        file_row = dict(row) if not isinstance(row, dict) else row
        chat_id, message_id = resolve_tg_message_id(file_row)
        if not chat_id or not message_id:
            continue
        key = (chat_id, message_id)
        if key in seen:
            continue
        seen.add(key)
        if delete_tg_message(chat_id, message_id, bot_token=bot_token):
            deleted += 1
    return deleted
