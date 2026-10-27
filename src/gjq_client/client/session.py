"""
HTTP 重试会话模块 (session.py)
====================================

核心网络通信引擎，基于 requests.Session 封装，提供：
    - Base URL 绑定与相对路径拼接
    - 认证头自动注入（通过 Auth 实例）
    - TCP 连接池复用（提高性能）
    - 自动重试机制（指数退避 + 随机抖动）
    - 调试日志与数据脱敏
    - 统一的超时与异常处理

所有 REST 适配器只需调用 session.request("GET", "/path")，
无需关心 URL 前缀、认证 Token 附加或网络重试逻辑。

使用示例::

    session = RetrySession(
        base_url="backend_url",
        auth=auth_instance,
    )
    response = session.request("GET", "/v1/guojisdk/getAvailableMachines")
"""

import time
import random
import logging
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from gjq_client.utils.exceptions import AuthenticationError, NetworkError, GJQTimeoutError

__all__ = ["RetrySession"]

logger = logging.getLogger(__name__)

# 默认可重试的 HTTP 状态码
RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# 非幂等：任务提交不做自动重试，避免重复建任务
_NON_RETRIABLE_PATH_MARKERS = ("/submitTask",)

# 日志脱敏时隐藏的 JSON 字段
_SENSITIVE_FIELDS = frozenset({"accessToken", "apiToken", "Authorization"})


class RetrySession:
    """核心网络通信引擎。

    绑定 base_url 后，所有请求只需传入相对路径。自动注入认证
    Header、管理连接池、在遇到可重试状态码或网络异常时按指数
    退避策略重试。

    Args:
        base_url: API 服务基础地址（如 "auth_url" 或 "backend_url"）。
        auth: 认证处理器实例（可选）。每次请求时自动调用
              auth.get_headers() 合并认证头。
        max_retries: 最大重试次数（不含首次请求），默认 3 次。
        backoff_factor: 退避基数（秒），默认 0.5 秒。
        max_backoff: 最大等待时间上限（秒），默认 60 秒。
        timeout: 单次请求超时（秒），默认 30 秒。
        retriable_status_codes: 触发重试的 HTTP 状态码集合。
    """

    def __init__(
        self,
        base_url: str,
        auth: Optional[Any] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        max_backoff: float = 60.0,
        timeout: float = 30.0,
        retriable_status_codes: frozenset[int] = RETRIABLE_STATUS_CODES,
        pq: Optional[Any] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._max_backoff = max_backoff
        self._timeout = timeout
        self._retriable_status_codes = retriable_status_codes

        # 创建 requests.Session 复用 TCP 连接
        self._session = requests.Session()

        # PQC 会话（惰性初始化）
        self._pq_session = None
        self._pq_gateway_url = None
        if pq is not None:
            self._init_pq(pq)

    def _init_pq(self, pq: dict) -> None:
        """初始化 PQC 会话（握手 + 指纹校验）。

        Args:
            pq: {"gateway_url": "http://...", "fingerprint": "sha256:..."}
        """
        from gjq_client.pqcrequests import PQSession

        gateway_url = pq["gateway_url"]
        fingerprint = pq.get("fingerprint")

        self._pq_gateway_url = gateway_url.rstrip("/")
        self._pq_session = PQSession(
            base_url=self._pq_gateway_url,
            server_fingerprint=fingerprint,
            gateway_path="",
        )
        logger.info("PQC session established (PQC 会话已建立), session_id=%s", self._pq_session.channel_id)

    @property
    def base_url(self) -> str:
        """返回当前绑定的 base_url。"""
        return self._base_url

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> requests.Response:
        """发送 HTTP 请求，自动拼接 base_url、注入认证头、失败时重试。

        当 PQC 启用时，请求通过 PQC Gateway 加密传输。

        Args:
            method: HTTP 方法（GET, POST, PUT, DELETE 等）。
            path: 相对路径（如 "/v1/guojisdk/getAvailableMachines"）。
            headers: 额外的 HTTP 请求头（会与认证头合并）。
            json: JSON 请求体（自动序列化）。
            data: 原始请求体。
            timeout: 本次请求的超时时间（覆盖默认值）。
            **kwargs: 传递给 requests.Session.request 的其他参数。

        Returns:
            requests.Response 对象。

        Raises:
            NetworkError: 所有重试均失败后的网络错误。
            GJQTimeoutError: 所有重试均超时。
        """
        request_timeout = timeout or self._timeout

        # ── PQC 路径：加密 → 代理发送 → 解密 ──────────────────────────
        if self._pq_session is not None:
            return self._pqc_request(method, path, headers, json, data, request_timeout, kwargs)

        # ── 标准路径 ──────────────────────────────────────────────────
        url = f"{self._base_url}{path}"

        # 合并认证头
        merged_headers = self._build_headers(headers)

        # 调试日志（脱敏）
        self._log_request_info(method, url, json)

        last_exception: Optional[Exception] = None
        allow_retry = self._allows_retry(method, path)

        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    headers=merged_headers,
                    json=json,
                    data=data,
                    timeout=request_timeout,
                    **kwargs,
                )

                # 检查是否需要重试
                if (
                    allow_retry
                    and response.status_code in self._retriable_status_codes
                    and attempt < self._max_retries
                ):
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request %s %s returned %d, retrying in %.1f s (%d/%d) "
                        "(请求返回 %d，%.1f 秒后重试 %d/%d)",
                        method, url, response.status_code,
                        wait_time, attempt + 1, self._max_retries,
                        response.status_code, wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                return response

            except requests.Timeout as e:
                last_exception = e
                if allow_retry and attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request %s %s timed out, retrying in %.1f s (%d/%d) "
                        "(请求超时，%.1f 秒后重试 %d/%d)",
                        method, url, wait_time, attempt + 1, self._max_retries,
                        wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                break

            except requests.ConnectionError as e:
                last_exception = e
                if allow_retry and attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request %s %s connection failed, retrying in %.1f s (%d/%d) "
                        "(请求连接失败，%.1f 秒后重试 %d/%d)",
                        method, url, wait_time, attempt + 1, self._max_retries,
                        wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                break

        # 所有重试均失败
        if isinstance(last_exception, requests.Timeout):
            raise GJQTimeoutError(
                f"Request {method} {url} timed out after {attempt + 1} attempts "
                f"(请求在 {attempt + 1} 次尝试后仍超时)"
            ) from last_exception

        raise NetworkError(
            f"Request {method} {url} failed after {attempt + 1} attempts "
            f"(请求在 {attempt + 1} 次尝试后仍失败): {last_exception}"
        ) from last_exception

    def _pqc_request(
        self,
        method: str,
        path: str,
        headers: Optional[dict],
        json_data: Optional[Any],
        raw_data: Optional[Any],
        timeout: float,
        request_kwargs: Optional[dict] = None,
    ) -> requests.Response:
        """PQC 加密代理请求：加密 → 发送到 Gateway → 解密响应。

        ``request_kwargs`` 中的 ``params`` 会被 urlencode 后拼接到加密
        payload 的 path 上（Gateway 原样转发 query string）；其余键值
        不被代理协议支持时显式报错，避免静默丢失。
        """
        import json as _json

        request_kwargs = dict(request_kwargs or {})
        params = request_kwargs.pop("params", None)
        if params:
            # requests 允许 params 为 str/bytes（已编码）或 dict
            if isinstance(params, str):
                query = params
            elif isinstance(params, bytes):
                query = params.decode()
            else:
                query = urlencode(params, doseq=True)
            path = f"{path}?{query}" if query else path
        if request_kwargs:
            unsupported = ", ".join(sorted(request_kwargs))
            raise ValueError(
                f"PQC proxy request does not support argument(s): {unsupported} "
                f"(PQC 代理请求不支持以下参数: {unsupported})"
            )

        merged_headers = self._build_headers(headers)

        body_bytes = None
        if json_data is not None:
            body_bytes = _json.dumps(json_data).encode()
        elif raw_data is not None:
            body_bytes = raw_data if isinstance(raw_data, bytes) else raw_data.encode()

        encrypted = self._pq_session.encrypt_request(
            method, path, merged_headers, body_bytes
        )
        proxy_headers = self._pq_session.proxy_headers()

        url = f"{self._pq_gateway_url}/proxy"
        self._log_request_info(method, url, None)
        logger.debug("PQC encrypted, session_id=%s", self._pq_session.channel_id)

        last_exception: Optional[Exception] = None
        allow_retry = self._allows_retry(method, path)

        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.request(
                    method="POST",
                    url=url,
                    headers=proxy_headers,
                    data=encrypted,
                    timeout=timeout,
                )

                if (
                    allow_retry
                    and response.status_code in self._retriable_status_codes
                    and attempt < self._max_retries
                ):
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "PQC proxy %s returned %d, retrying in %.1f s (%d/%d)",
                        url, response.status_code,
                        wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                if response.status_code == 401:
                    # channel 失效（如 Gateway 重启、证书重新生成）→
                    # 重新握手建立新 channel，用新密钥重新加密后重试。
                    # 提交类请求（allow_retry=False）不重发，避免重复建任务。
                    if not allow_retry or attempt >= self._max_retries:
                        last_exception = RuntimeError(
                            f"PQC channel rejected (PQC 通道被拒绝): {response.text[:200]}"
                        )
                        break
                    try:
                        self._rehandshake()
                        proxy_headers = self._pq_session.proxy_headers()
                        encrypted = self._pq_session.encrypt_request(
                            method, path, merged_headers, body_bytes
                        )
                        continue
                    except Exception as e:
                        last_exception = e
                        logger.warning("PQC re-handshake failed: %s", e)
                        break

                try:
                    return self._pq_session.decrypt_response(response.content)
                except Exception as e:
                    raise NetworkError(
                        f"PQC response decryption failed: {e}"
                    ) from e

            except requests.Timeout as e:
                last_exception = e
                if allow_retry and attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "PQC proxy %s timed out, retrying in %.1f s (%d/%d)",
                        url, wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

            except requests.ConnectionError as e:
                last_exception = e
                if allow_retry and attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "PQC proxy %s connection failed, retrying in %.1f s (%d/%d)",
                        url, wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

        if isinstance(last_exception, requests.Timeout):
            raise GJQTimeoutError(
                f"PQC proxy POST {url} timed out after {self._max_retries + 1} attempts"
            ) from last_exception

        if last_exception is None:
            # 循环正常走完且全是 401：每次重握手后新 channel 仍被拒绝。
            last_exception = RuntimeError(
                "PQC channel keeps being rejected after re-handshake "
                "(PQC 通道重握手后仍被拒绝)"
            )

        raise NetworkError(
            f"PQC proxy POST {url} failed after {self._max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    def _rehandshake(self) -> None:
        """重新执行 PQC 握手，替换失效的加密通道。

        在 Gateway 重启或证书重新生成后，旧 channel_id 在服务端已不存在
        （/proxy 返回 401）。重新协商即可恢复，无需重建整个客户端。
        """
        from gjq_client.pqcrequests import PQSession

        old = self._pq_session
        self._pq_session = PQSession(
            base_url=self._pq_gateway_url,
            server_fingerprint=old._fp,
        )
        logger.info(
            "PQC channel re-established (PQC 通道已重建), old=%s new=%s",
            old.channel_id, self._pq_session.channel_id,
        )
        try:
            old.close()
        except Exception:
            pass

    def _build_headers(self, extra_headers: Optional[dict] = None) -> dict:
        """合并认证头和额外请求头。

        优先级: extra_headers > auth headers > 默认 Content-Type。
        """
        headers = {"Content-Type": "application/json"}

        # 注入认证头
        if self._auth is not None:
            try:
                auth_headers = self._auth.get_headers()
                headers.update(auth_headers)
            except Exception as exc:
                raise AuthenticationError(
                    "Failed to get authentication headers (获取认证头失败)"
                ) from exc

        # 合并额外头
        if extra_headers:
            headers.update(extra_headers)

        return headers

    def _log_request_info(
        self,
        method: str,
        url: str,
        json_body: Optional[Any] = None,
    ) -> None:
        """记录请求调试日志（自动脱敏敏感字段）。"""
        if not logger.isEnabledFor(logging.DEBUG):
            return

        safe_body = None
        if json_body and isinstance(json_body, dict):
            safe_body = {
                k: ("***" if k in _SENSITIVE_FIELDS else v)
                for k, v in json_body.items()
            }

        logger.debug("Request: %s %s body=%s", method, url, safe_body)

    @staticmethod
    def _allows_retry(method: str, path: str) -> bool:
        """Task submission and Session creation must not be duplicated."""
        path = path or ""
        if any(marker in path for marker in _NON_RETRIABLE_PATH_MARKERS):
            return False
        if method.upper() == "POST" and path.rstrip("/").endswith("/sessions"):
            return False
        return True

    def _calculate_backoff(self, attempt: int) -> float:
        """计算第 N 次重试的等待时间（指数退避 + 随机抖动）。

        公式: wait = min(backoff_factor * 2^attempt + jitter, max_backoff)
        """
        delay = self._backoff_factor * (2 ** attempt)
        jitter = random.uniform(0, delay * 0.1)
        return min(delay + jitter, self._max_backoff)

    def close(self) -> None:
        """关闭 HTTP 会话与 PQC 加密通道，释放连接池资源。"""
        if self._pq_session is not None:
            try:
                self._pq_session.close()
            except Exception:
                logger.debug("PQC session close failed", exc_info=True)
            self._pq_session = None
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
