"""
PQC 密码学原语封装。

基于 ``cryptography`` 库提供：
    - ML-KEM768  密钥封装（FIPS 203）
    - ML-DSA44   数字签名（FIPS 204）
    - AES-256-GCM 对称加密
    - SHAKE-256   密钥派生
"""

from __future__ import annotations

import hashlib
import os
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.mlkem import (
    MLKEM768PrivateKey,
    MLKEM768PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.mldsa import (
    MLDSA44PrivateKey,
    MLDSA44PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

__all__ = [
    "ML_KEM",
    "ML_DSA",
    "PQKeyDerivation",
    "AESGCMCipher",
]

# ── 常量 ────────────────────────────────────────────────────────────────
# 密钥 / 密文 / 签名长度（字节），遵循 FIPS 203 / 204
AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 12
HANDSHAKE_TIME_WINDOW_S = 300  # 握手防重放窗口（秒）


# ========================================================================
# ML-KEM768  密钥封装
# ========================================================================


class ML_KEM:
    """ML-KEM768 密钥封装机制（FIPS 203）。"""

    @staticmethod
    def generate_keypair() -> Tuple[MLKEM768PublicKey, MLKEM768PrivateKey]:
        """生成密钥对，返回 (公钥, 私钥)。"""
        sk = MLKEM768PrivateKey.generate()
        return sk.public_key(), sk

    @staticmethod
    def encapsulate(pk: MLKEM768PublicKey) -> Tuple[bytes, bytes]:
        """封装共享密钥，返回 (共享密钥 32 B, 密文 1088 B)。"""
        ss, ct = pk.encapsulate()
        return ss, ct

    @staticmethod
    def decapsulate(sk: MLKEM768PrivateKey, ct: bytes) -> bytes:
        """解封装，返回 32 字节共享密钥。"""
        return sk.decapsulate(ct)

    @staticmethod
    def pubkey_bytes(pk: MLKEM768PublicKey) -> bytes:
        """序列化公钥为原始字节（1184 B）。"""
        return pk.public_bytes_raw()

    @staticmethod
    def seed_bytes(sk: MLKEM768PrivateKey) -> bytes:
        """序列化私钥种子（64 B）。"""
        return sk.private_bytes_raw()

    @staticmethod
    def pubkey_from_bytes(data: bytes) -> MLKEM768PublicKey:
        """从原始字节反序列化公钥。"""
        return MLKEM768PublicKey.from_public_bytes(data)

    @staticmethod
    def privkey_from_seed(seed: bytes) -> MLKEM768PrivateKey:
        """从种子反序列化私钥。"""
        return MLKEM768PrivateKey.from_seed_bytes(seed)


# ========================================================================
# ML-DSA44  数字签名
# ========================================================================


class ML_DSA:
    """ML-DSA44 数字签名算法（FIPS 204）。"""

    @staticmethod
    def generate_keypair() -> Tuple[MLDSA44PublicKey, MLDSA44PrivateKey]:
        """生成密钥对，返回 (公钥, 私钥)。"""
        sk = MLDSA44PrivateKey.generate()
        return sk.public_key(), sk

    @staticmethod
    def sign(sk: MLDSA44PrivateKey, data: bytes) -> bytes:
        """对数据签名，返回约 2420 字节签名。"""
        return sk.sign(data)

    @staticmethod
    def verify(pk: MLDSA44PublicKey, data: bytes, signature: bytes) -> None:
        """验证签名。验证失败抛出 ``InvalidSignature``。"""
        pk.verify(signature, data)

    @staticmethod
    def pubkey_bytes(pk: MLDSA44PublicKey) -> bytes:
        """序列化公钥为原始字节（1312 B）。"""
        return pk.public_bytes_raw()

    @staticmethod
    def seed_bytes(sk: MLDSA44PrivateKey) -> bytes:
        """序列化私钥种子（32 B）。"""
        return sk.private_bytes_raw()

    @staticmethod
    def sk_bytes(sk: MLDSA44PrivateKey) -> bytes:
        """序列化私钥为原始字节（2560 B），完整可恢复，用于持久化存储。"""
        return sk.private_bytes_raw()

    @staticmethod
    def sk_from_bytes(data: bytes) -> MLDSA44PrivateKey:
        """从原始字节反序列化私钥。"""
        return MLDSA44PrivateKey.from_seed_bytes(data)

    @staticmethod
    def pubkey_from_bytes(data: bytes) -> MLDSA44PublicKey:
        """从原始字节反序列化公钥。"""
        return MLDSA44PublicKey.from_public_bytes(data)

    @staticmethod
    def privkey_from_seed(seed: bytes) -> MLDSA44PrivateKey:
        """从种子反序列化私钥。"""
        return MLDSA44PrivateKey.from_seed_bytes(seed)


# ========================================================================
# SHAKE-256  密钥派生
# ========================================================================


class PQKeyDerivation:
    """通过 SHAKE-256 从 ML-KEM768 共享密钥派生 AES-256 密钥。"""

    @staticmethod
    def derive_key(shared_secret: bytes, context: bytes = b"gjq-pqc-session") -> bytes:
        """从共享密钥派生 32 字节 AES-256 密钥。

        Args:
            shared_secret: ML-KEM768 共享密钥（32 字节）。
            context: 域分离上下文字符串。
        """
        return hashlib.shake_256(shared_secret + context).digest(AES_KEY_BYTES)


# ========================================================================
# AES-256-GCM  对称加密
# ========================================================================


class AESGCMCipher:
    """AES-256-GCM 加密，每次加密使用随机 nonce。"""

    def __init__(self, key: bytes):
        if len(key) != AES_KEY_BYTES:
            raise ValueError(f"AES 密钥必须为 {AES_KEY_BYTES} 字节，实际为 {len(key)}")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        """加密明文，返回 (nonce + 密文 + 认证标签) 的拼接。"""
        nonce = os.urandom(GCM_NONCE_BYTES)
        ct = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, blob: bytes) -> bytes:
        """解密由 ``encrypt()`` 生成的密文 blob。"""
        nonce = blob[:GCM_NONCE_BYTES]
        ct = blob[GCM_NONCE_BYTES:]
        return self._aesgcm.decrypt(nonce, ct, None)
