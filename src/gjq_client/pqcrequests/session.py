"""
客户端 PQC 会话。

管理三个阶段通信並具備 TLS 級別的握手重試機制：

    1.  GET  {gateway_path}/cert      — 获取服务端证书并验签
    2.  POST {gateway_path}/handshake — ML-KEM768 密钥协商
    3.  POST {gateway_path}/proxy     — AES-256-GCM 加密通信

握手階段網絡錯誤（連接拒絕、超時、HTTP 5xx）最多重試 3 次，指數退避。
安全校驗失敗（指紋不匹配、證書過期、簽名無效）不重試，直接拒絕。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional

import requests

from .crypto import (
    ML_KEM,
    ML_DSA,
    PQKeyDerivation,
    AESGCMCipher,
)
from .cert import PQCertificate, cert_fingerprint
from .headers import X_PQ_CHANNEL_ID

__all__ = ["PQSession"]

logger = logging.getLogger(__name__)

# ── 握手重試常量 ──────────────────────────────────────────────────────────
_MAX_HANDSHAKE_ATTEMPTS = 3
# HTTP 狀態碼：網絡錯誤（值得重試）
_RETRIABLE_HTTP_CODES = frozenset(range(500, 600))


class PQSession:
    """客户端 PQC 会话，与 PQC Gateway 协商共享 AES-256 密钥后加密后续 API 请求。

    Args:
        base_url: PQC Gateway 根地址（如 ``"http://127.0.0.1:8443"``）。
        server_fingerprint: 服务端证书 SHA-256 指纹，用于防止中间人攻击。
            格式为 ``"sha256:hex..."``。使用 ``cert_fingerprint()`` 从
            服务端证书生成。留 ``None`` 则跳过验证（仅调试用）。
        session: 可选，已有 ``requests.Session`` 对象，用于连接复用。
        gateway_path: Gateway 挂载路径，默认 ``""``。
    """

    def __init__(
        self,
        base_url: str,
        server_fingerprint: str | None = None,
        session: Optional[requests.Session] = None,
        gateway_path: str = "",
    ):
        self._base_url = base_url.rstrip("/")
        self._gateway_path = gateway_path
        self._fp = server_fingerprint
        self._http = session or requests.Session()

        self._aes: Optional[AESGCMCipher] = None
        self.channel_id: Optional[str] = None

        # 构造函数中自动完成握手（带重试）
        self._handshake()

    # ── 公开 API ────────────────────────────────────────────────────────

    def encrypt_request(
        self,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        body: Optional[bytes | str] = None,
    ) -> bytes:
        """构建并加密代理请求载荷。

        返回 AES-GCM 加密后的二进制数据，可直接作为
        ``POST {gateway_path}/proxy`` 的请求体发送。
        """
        if self._aes is None:
            raise RuntimeError("PQC 会话未建立——需先完成握手")

        body_b64 = None
        if body is not None:
            if isinstance(body, str):
                body = body.encode()
            body_b64 = base64.urlsafe_b64encode(body).decode()

        payload = json.dumps(
            {
                "method": method,
                "path": path,
                "headers": {k: v for k, v in (headers or {}).items()},
                "body_b64": body_b64,
            }
        ).encode()
        return self._aes.encrypt(payload)

    def decrypt_response(self, encrypted: bytes) -> requests.Response:
        """解密 PQC 代理响应并重建 ``requests.Response`` 对象。

        Args:
            encrypted: ``POST {gateway_path}/proxy`` 响应体原始字节。

        Returns:
            合成的 ``requests.Response``，其 ``.status_code`` 和 ``.json()``
            与解密后的上游响应一致。
        """
        if self._aes is None:
            raise RuntimeError("PQC 会话未建立")

        decrypted = self._aes.decrypt(encrypted)
        payload = json.loads(decrypted)

        resp = requests.Response()
        resp.status_code = payload["status"]
        resp._content = base64.urlsafe_b64decode(payload["body_b64"] or "")
        # 还原上游响应头
        for k, v in (payload.get("headers") or {}).items():
            resp.headers[k] = v
        resp.encoding = "utf-8"
        return resp

    def proxy_headers(self) -> dict:
        """返回每次代理请求必须携带的 HTTP 头。"""
        if not self.channel_id:
            raise RuntimeError("PQC 会话未建立")
        return {X_PQ_CHANNEL_ID: self.channel_id}

    # ── 握手 ────────────────────────────────────────────────────────────

    def _handshake(self) -> None:
        """执行 PQC 握手，网络错误时最多重试 3 次（指数退避）。

        安全校验失败不重试：
        - 指纹不匹配  → 直接拒绝（等价于 TLS 证书链校验失败）
        - 证书过期    → 直接拒绝
        - 签名无效    → 直接拒绝
        - HTTP 4xx    → 直接拒绝（请求格式错误）
        """
        last_error: Optional[Exception] = None

        for attempt in range(_MAX_HANDSHAKE_ATTEMPTS):
            try:
                self._do_handshake()
                return
            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = e
                if attempt < _MAX_HANDSHAKE_ATTEMPTS - 1:
                    wait = 0.5 * (2**attempt)
                    logger.warning(
                        "PQC 握手第 %d/%d 次网络失败，%.1f 秒后重试",
                        attempt + 1, _MAX_HANDSHAKE_ATTEMPTS, wait,
                    )
                    time.sleep(wait)
            except requests.HTTPError as e:
                # 5xx → 重试，4xx → 直接抛
                if (
                    e.response is not None
                    and e.response.status_code in _RETRIABLE_HTTP_CODES
                    and attempt < _MAX_HANDSHAKE_ATTEMPTS - 1
                ):
                    last_error = e
                    wait = 0.5 * (2**attempt)
                    logger.warning(
                        "PQC 握手第 %d/%d 次服务端错误 %d，%.1f 秒后重试",
                        attempt + 1, _MAX_HANDSHAKE_ATTEMPTS,
                        e.response.status_code, wait,
                    )
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(
            f"PQC 握手失败，已重试 {_MAX_HANDSHAKE_ATTEMPTS} 次: {last_error}"
        ) from last_error

    def _do_handshake(self) -> None:
        """单次 PQC 握手（无重试），任何阶段失败则放弃本次尝试。"""
        # 阶段 1: 获取服务端证书并验证指纹
        server_cert = self._fetch_server_cert()

        if self._fp is not None:
            actual = cert_fingerprint(server_cert)
            if actual != self._fp:
                raise RuntimeError(
                    f"服务端证书指纹不匹配！期望: {self._fp}, 实际: {actual}"
                )

        # 阶段 2: ML-KEM768 密钥协商（不发送客户端证书）
        kem_pk, kem_sk = ML_KEM.generate_keypair()
        kem_pk_bytes = ML_KEM.pubkey_bytes(kem_pk)

        hs_resp = self._post(
            f"{self._gateway_path}/handshake",
            {
                "encap_key": base64.urlsafe_b64encode(kem_pk_bytes).decode(),
                "timestamp": int(time.time()),
            },
        )
        hs_data = hs_resp.json()

        server_ct = base64.urlsafe_b64decode(hs_data["ciphertext"])
        channel_id = hs_data["channel_id"]
        server_sig = base64.urlsafe_b64decode(hs_data["server_sig"])
        ML_DSA.verify(server_cert.public_key, server_ct + channel_id.encode(), server_sig)

        shared_secret = ML_KEM.decapsulate(kem_sk, server_ct)
        aes_key = PQKeyDerivation.derive_key(shared_secret)

        self._aes = AESGCMCipher(aes_key)
        self.channel_id = channel_id

    # ── 内部辅助方法 ────────────────────────────────────────────────────

    def _fetch_server_cert(self) -> PQCertificate:
        """获取并验证服务端 PQC 证书。"""
        resp = self._get(f"{self._gateway_path}/cert")
        data = resp.json()
        cert = PQCertificate.from_json(data["cert"])
        cert.verify()
        return cert

    def _get(self, path: str) -> requests.Response:
        resp = self._http.get(f"{self._base_url}{path}", timeout=30)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, json_body: dict) -> requests.Response:
        resp = self._http.post(
            f"{self._base_url}{path}",
            json=json_body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    def close(self) -> None:
        """通知 Gateway 释放加密通道，并关闭底层 HTTP 会话。

        通知失败（网络不通等）不影响本地清理；Gateway 侧通道由
        服务端自行回收。
        """
        if self._aes is not None and self.channel_id:
            try:
                self._http.delete(
                    f"{self._base_url}{self._gateway_path}/session",
                    headers={X_PQ_CHANNEL_ID: self.channel_id},
                    timeout=5,
                )
            except Exception:
                logger.debug("PQC channel release failed", exc_info=True)
            self._aes = None
        self._http.close()