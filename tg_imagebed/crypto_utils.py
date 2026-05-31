#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AES-256-GCM 加密/解密工具

格式: ENC:AESGCM:<base64(nonce||ciphertext||tag)>

密钥来源: config.SECRET_KEY (SHA-256 哈希后作为 AES-256 密钥)
"""

import base64
import hashlib
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import logger, SECRET_KEY

# ── 加密前缀 ─────────────────────────────────────────
ENC_PREFIX = b"ENC:AESGCM:"
NONCE_LENGTH = 12

# ── 密钥缓存 ────────────────────────────────────────
_cipher_key: Optional[bytes] = None


def _derive_key(raw_key: str) -> bytes:
    """将原始密钥 SHA-256 哈希为 32 字节 AES-256 密钥"""
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def get_encryption_key() -> bytes:
    """获取加密密钥（从 SECRET_KEY SHA-256 派生，带缓存）"""
    global _cipher_key
    if _cipher_key is not None:
        return _cipher_key
    _cipher_key = _derive_key(SECRET_KEY)
    return _cipher_key


def clear_encryption_key_cache() -> None:
    """清除密钥缓存（用于密钥轮换）"""
    global _cipher_key, _KEY_SOURCE
    _cipher_key = None
    _KEY_SOURCE = ""


def _raw_encrypt(plaintext: bytes) -> bytes:
    """AES-256-GCM 加密 (底层，返回 nonce + ciphertext + tag)"""
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    # GCM 的 encrypt() 返回 ciphertext + 16-byte tag
    return nonce + ciphertext


def _raw_decrypt(payload: bytes) -> bytes:
    """AES-256-GCM 解密 (底层，payload = nonce + ciphertext + tag)"""
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = payload[:NONCE_LENGTH]
    encrypted = payload[NONCE_LENGTH:]
    return aesgcm.decrypt(nonce, encrypted, None)


def encrypt_value(plaintext: str) -> str:
    """
    加密字符串。空字符串直接返回空串。

    Returns:
        Base64 编码的密文，格式: ENC:AESGCM:<base64>
    """
    if not plaintext:
        return ""

    try:
        raw = _raw_encrypt(plaintext.encode("utf-8"))
        b64 = base64.urlsafe_b64encode(raw).decode("ascii")
        return (ENC_PREFIX + b64.encode("ascii")).decode("ascii")
    except Exception as e:
        logger.error(f"加密失败: {e}")
        # 加密失败时返回明文 (fail-open，避免锁死数据)
        return plaintext


def decrypt_value(value: str) -> str:
    """
    解密字符串。

    如果是 ENC:AESGCM: 前缀则解密，否则直接返回原值 (向后兼容明文)。
    空字符串直接返回空串。
    """
    if not value:
        return ""

    try:
        if value.startswith("ENC:AESGCM:"):
            b64_str = value[len("ENC:AESGCM:"):]
            raw = base64.urlsafe_b64decode(b64_str)
            return _raw_decrypt(raw).decode("utf-8")
        else:
            # 明文存储的旧值 — 保持向后兼容
            return value
    except Exception as e:
        logger.error(
            f"解密失败 (密钥可能已变更?): 输入长度={len(value)}, "
            f"前缀={value[:20]}..., 错误={e}"
        )
        if value.startswith("ENC:AESGCM:"):
            logger.warning("返回密文原始值（解密失败）")
        return value


def is_encrypted(value: str) -> bool:
    """检查值是否已加密"""
    return bool(value) and value.startswith("ENC:AESGCM:")


def re_encrypt_value(value: str) -> str:
    """
    重新加密值 (密钥轮换用)

    解密旧密钥 → 用新密钥加密
    """
    plaintext = decrypt_value(value)
    if plaintext == value and is_encrypted(value):
        # 解密失败 — 不要覆盖
        logger.warning("重新加密跳过：解密失败")
        return value
    return encrypt_value(plaintext)
