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
from typing import Optional, Any

import requests

from gjq_client.utils.exceptions import NetworkError, GJQTimeoutError

__all__ = ["RetrySession"]

logger = logging.getLogger(__name__)

# 默认可重试的 HTTP 状态码
RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

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
        url = f"{self._base_url}{path}"
        request_timeout = timeout or self._timeout

        # 合并认证头
        merged_headers = self._build_headers(headers)

        # 调试日志（脱敏）
        self._log_request_info(method, url, json)

        last_exception: Optional[Exception] = None

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
                if response.status_code in self._retriable_status_codes:
                    if attempt < self._max_retries:
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
                    # 最后一次重试也失败了，仍然返回 response

                return response

            except requests.Timeout as e:
                last_exception = e
                if attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request %s %s timed out, retrying in %.1f s (%d/%d) "
                        "(请求超时，%.1f 秒后重试 %d/%d)",
                        method, url, wait_time, attempt + 1, self._max_retries,
                        wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

            except requests.ConnectionError as e:
                last_exception = e
                if attempt < self._max_retries:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request %s %s connection failed, retrying in %.1f s (%d/%d) "
                        "(请求连接失败，%.1f 秒后重试 %d/%d)",
                        method, url, wait_time, attempt + 1, self._max_retries,
                        wait_time, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait_time)
                    continue

        # 所有重试均失败
        if isinstance(last_exception, requests.Timeout):
            raise GJQTimeoutError(
                f"Request {method} {url} timed out after {self._max_retries + 1} attempts "
                f"(请求在 {self._max_retries + 1} 次尝试后仍超时)"
            ) from last_exception

        raise NetworkError(
            f"Request {method} {url} failed after {self._max_retries + 1} attempts "
            f"(请求在 {self._max_retries + 1} 次尝试后仍失败): {last_exception}"
        ) from last_exception

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
            except Exception:
                logger.debug("Failed to get authentication headers, request will be sent unauthenticated (获取认证头失败，将在无认证状态下发送请求)")

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

    def _calculate_backoff(self, attempt: int) -> float:
        """计算第 N 次重试的等待时间（指数退避 + 随机抖动）。

        公式: wait = min(backoff_factor * 2^attempt + jitter, max_backoff)
        """
        delay = self._backoff_factor * (2 ** attempt)
        jitter = random.uniform(0, delay * 0.1)
        return min(delay + jitter, self._max_backoff)

    def close(self) -> None:
        """关闭 HTTP 会话，释放连接池资源。"""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
