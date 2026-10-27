"""
PQC 自签名证书。

每张证书将 ML-DSA44 公钥绑定到一个主体标识，并包含有效期。
证书使用自身私钥签名（自签名），以 JSON + base64 信封格式序列化。
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .crypto import ML_DSA
from cryptography.hazmat.primitives.asymmetric.mldsa import (
    MLDSA44PublicKey,
    MLDSA44PrivateKey,
)

__all__ = ["PQCertificate", "cert_fingerprint"]


def cert_fingerprint(cert: "PQCertificate") -> str:
    """返回证书的 SHA-256 指纹，格式为 ``sha256:hex...``。"""
    h = hashlib.sha256(cert._as_dict().get("public_key_b64", "").encode()).hexdigest()
    return f"sha256:{h[:32]}"


@dataclass
class PQCertificate:
    """自签名 PQC 证书。

    Attributes:
        subject: 主体标识（如 ``"server:gjq-gateway"``、``"client:user-a"``）。
        public_key: 主体的 ML-DSA44 公钥。
        not_before: 有效期起始时间（UTC）。
        not_after: 有效期截止时间（UTC）。
        signature: ML-DSA44 对 TBS（待签名数据）的签名。
    """

    subject: str
    public_key: MLDSA44PublicKey
    not_before: datetime
    not_after: datetime
    signature: bytes = b""

    # ── 工厂方法 ────────────────────────────────────────────────────────

    @classmethod
    def self_signed(
        cls,
        subject: str,
        private_key: MLDSA44PrivateKey,
        validity_years: int = 10,
    ) -> "PQCertificate":
        """创建自签名证书。

        Args:
            subject: 主体标识。
            private_key: ML-DSA44 私钥（公钥从中派生）。
            validity_years: 证书有效期（年），默认 10 年。
        """
        now = datetime.now(timezone.utc)
        cert = cls(
            subject=subject,
            public_key=private_key.public_key(),
            not_before=now,
            not_after=datetime(now.year + validity_years, now.month, now.day,
                               tzinfo=timezone.utc),
        )
        cert.signature = ML_DSA.sign(private_key, cert._tbs_bytes())
        return cert

    # ── 序列化 ──────────────────────────────────────────────────────────

    def to_json(self) -> str:
        """序列化证书为 JSON 字符串。"""
        return json.dumps(self._as_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "PQCertificate":
        """从 JSON 字符串反序列化证书。"""
        d = json.loads(data)
        return cls(
            subject=d["subject"],
            public_key=ML_DSA.pubkey_from_bytes(
                base64.urlsafe_b64decode(d["public_key_b64"])
            ),
            not_before=datetime.fromisoformat(d["not_before"]),
            not_after=datetime.fromisoformat(d["not_after"]),
            signature=base64.urlsafe_b64decode(d["signature_b64"]),
        )

    # ── 验证 ────────────────────────────────────────────────────────────

    def is_expired(self) -> bool:
        """检查证书是否已过期。"""
        now = datetime.now(timezone.utc)
        return now < self.not_before or now > self.not_after

    def verify(self) -> None:
        """验证证书自签名。

        Raises:
            InvalidSignature: 签名无效。
            ValueError: 证书已过期。
        """
        if self.is_expired():
            raise ValueError(
                f"证书 '{self.subject}' 已过期 "
                f"（有效期 {self.not_before.isoformat()} – {self.not_after.isoformat()}）"
            )
        ML_DSA.verify(self.public_key, self._tbs_bytes(), self.signature)

    # ── 内部方法 ────────────────────────────────────────────────────────

    def _tbs_bytes(self) -> bytes:
        """待签名数据（除 signature 外的所有字段）。"""
        return json.dumps(
            {k: v for k, v in self._as_dict().items() if k != "signature_b64"},
            sort_keys=True,
        ).encode()

    def _as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "public_key_b64": base64.urlsafe_b64encode(
                ML_DSA.pubkey_bytes(self.public_key)
            ).decode(),
            "not_before": self.not_before.isoformat(),
            "not_after": self.not_after.isoformat(),
            "signature_b64": base64.urlsafe_b64encode(self.signature).decode(),
        }
