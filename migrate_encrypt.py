#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据迁移脚本 — 将 admin_config 中的明文敏感数据加密存储

用法:
    python3 migrate_encrypt.py

    # 预览模式 (不写入，仅查看将迁移哪些)
    python3 migrate_encrypt.py --dry-run

加密密钥直接使用 config.py 中的 SECRET_KEY，无需额外配置。
"""
import sys
import os
import argparse

# 确保能导入 tg_imagebed
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from tg_imagebed.database.connection import get_connection
from tg_imagebed.database.settings import SENSITIVE_SETTINGS
from tg_imagebed.crypto_utils import encrypt_value, is_encrypted
from tg_imagebed.config import logger


def migrate(dry_run: bool = False) -> dict:
    """迁移敏感数据: 明文 → 加密"""

    stats = {"scanned": 0, "already_encrypted": 0, "encrypted": 0, "skipped_empty": 0}

    with get_connection() as conn:
        cursor = conn.cursor()

        for key in sorted(SENSITIVE_SETTINGS):
            cursor.execute(
                "SELECT key, value FROM admin_config WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            if not row:
                continue

            current_value = row["value"]
            if not current_value:
                stats["skipped_empty"] += 1
                continue

            stats["scanned"] += 1

            if is_encrypted(current_value):
                stats["already_encrypted"] += 1
                logger.info(f"  ✓ {key}: 已加密，跳过")
                continue

            # 明文 — 加密并写回
            encrypted = encrypt_value(current_value)

            if dry_run:
                stats["encrypted"] += 1
                logger.info(
                    f"  🔒 {key}: 将加密 (明文长度={len(current_value)})"
                )
            else:
                cursor.execute(
                    "UPDATE admin_config SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (encrypted, key),
                )
                stats["encrypted"] += 1
                logger.info(
                    f"  🔒 {key}: 已加密 (明文 {len(current_value)} 字符 → 密文 {len(encrypted)} 字符)"
                )

    return stats


def main():
    parser = argparse.ArgumentParser(description="迁移敏感数据: 明文 → AES-GCM 加密")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际写入",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="迁移后验证 (读取并解密所有敏感字段)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("敏感数据加密迁移")
    print("=" * 60)

    if args.verify:
        print("\n[验证模式] 读取所有敏感字段并验证解密...")
        from tg_imagebed.crypto_utils import decrypt_value

        with get_connection() as conn:
            cursor = conn.cursor()
            all_ok = True
            for key in sorted(SENSITIVE_SETTINGS):
                cursor.execute(
                    "SELECT key, value FROM admin_config WHERE key = ?", (key,)
                )
                row = cursor.fetchone()
                if not row:
                    print(f"  ⚠️  {key}: 未找到记录")
                    continue

                value = row["value"]
                if not value:
                    print(f"  - {key}: (空值)")
                    continue

                if is_encrypted(value):
                    try:
                        plaintext = decrypt_value(value)
                        print(
                            f"  ✓ {key}: 已加密, 可正常解密 "
                            f"(长度 {len(value)}/{len(plaintext)})"
                        )
                    except Exception as e:
                        print(f"  ✗ {key}: 解密失败 — {e}")
                        all_ok = False
                else:
                    print(f"  ⚠️  {key}: 明文存储 (未迁移?)")
                    all_ok = False

        if all_ok:
            print("\n✅ 所有敏感字段加密正常")
        else:
            print("\n⚠️  存在未加密字段，请运行迁移")
        return

    stats = migrate(dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("迁移统计:")
    print(f"  扫描: {stats['scanned']}")
    print(f"  已加密(跳过): {stats['already_encrypted']}")
    print(f"  加密: {stats['encrypted']}")
    print(f"  跳过空值: {stats['skipped_empty']}")
    print("=" * 60)

    if args.dry_run:
        print("\n(预览模式 — 未写入数据库)")
    elif stats["encrypted"] > 0:
        print("\n✅ 迁移完成! 请运行 --verify 验证。")
    else:
        print("\n📭 没有需要迁移的明文数据")


if __name__ == "__main__":
    main()
