"""
客户端连接参数模块 (client_parameters.py)
==========================================

管理客户端连接参数，包括：
    - 服务地址 (base_url)
    - API Key 存储
    - JWT access_token 的获取、缓存与自动刷新
    - Token 过期检测（基于服务端返回的 expireAtTime 绝对时间戳）

认证流程::

    1. 用户传入 api_key
    2. 调用 POST /user/api/tokens 获取 JWT apiToken + expireAtTime
    3. 缓存 token 和过期时间戳
    4. 每次使用前检查是否过期（提前 60 秒刷新）
    5. 过期则用 api_key 重新调用认证接口

使用示例::

    params = ClientParameters(
        api_key="api_key",
        base_url="auth_url"
    )
    params.authenticate()          # 首次获取 token
    token = params.access_token    # 获取当前有效的 token
    if params.token_expired():
        params.refresh_token()     # 自动刷新
"""

import time
import logging
import base64
from typing import Optional

import requests

from gjq_client.utils.exceptions import (
    AuthenticationError,
    ConfigurationError,
    APIError,
    NetworkError,
)

from .backend_url_config import decrypt_url,DEFAULT_BASE_URL

__all__ = ["ClientParameters"]

logger = logging.getLogger(__name__)


# Token 提前刷新的缓冲时间（秒）
TOKEN_REFRESH_BUFFER = 60


class ClientParameters:
    """客户端连接参数管理器。

    负责管理 API Key、服务地址、JWT access_token 的生命周期，
    包括首次获取、过期检测和自动刷新。

    Attributes:
        access_token: 当前有效的 JWT access_token，未认证时为 None。

    Args:
        api_key: 用户的 API Key。
        base_url: 认证 API 基础地址覆盖，默认 None（使用内置地址）。
        backend_url: 后端查询 API 基础地址覆盖，默认 None（使用内置地址）。
        channel: 平台渠道名称。

    Raises:
        ConfigurationError: api_key 为空时抛出。
    """

    def __init__(
        self,
        api_key: str,
        channel: str = "gjq_cloud",
        base_url: Optional[str] = None,
        backend_url: Optional[str] = None,
    ):
        if not api_key or not api_key.strip():
            raise ConfigurationError("api_key cannot be empty (api_key 不能为空)")

        self.channel: str = channel
        self._api_key: str = api_key.strip()

        self._base_override = base_url.rstrip("/") if base_url else None
        self._backend_override = backend_url.rstrip("/") if backend_url else None

        # JWT token 相关状态
        self.access_token: Optional[str] = None
        self._expire_at: Optional[float] = None       # token 过期时间（秒级时间戳）
        self._user_id: Optional[str] = None           # 用户 ID

    # ==========================================================================
    # 公共方法
    # ==========================================================================

    def authenticate(self) -> dict:
        """使用 api_key 调用认证接口获取 JWT access_token。

        调用 POST /user/api/tokens，成功后缓存 token 及过期时间。

        Returns:
            认证接口返回的 data 字典，包含 apiToken, userId, expireAtTime 等。

        Raises:
            AuthenticationError: api_key 无效或认证失败。
            NetworkError: 网络连接失败。
            APIError: API 返回业务错误。
        """
        base_url=self._base_override or decrypt_url(b'Ry8h9VgUXWpCCKQwcbEB8w==',DEFAULT_BASE_URL)
        url = f"{base_url}/user/api/tokens"
        logger.info("Authenticating (正在认证)... (POST /user/api/tokens)")

        try:
            response = requests.post(
                url,
                json={"accessToken": self._api_key},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
        except requests.ConnectionError as e:
            raise NetworkError(f"Failed to connect to authentication service (无法连接到认证服务): {e}") from e
        except requests.Timeout as e:
            raise NetworkError(f"Authentication request timeout (认证请求超时): {e}") from e

        # 解析 JSON 响应
        try:
            body = response.json()
        except ValueError:
            raise APIError(
                message="Authentication response parsing failed, non-JSON format (认证响应解析失败，非 JSON 格式)",
                status_code=response.status_code,
            )

        # 按业务状态码处理
        code = body.get("code")

        if response.status_code != 200:
            raise APIError(
                message=body.get("message", "Authentication failed (认证失败)"),
                status_code=response.status_code,
                response_body=body,
            )

        if code == 80006:
            raise AuthenticationError(
                "User access token not found, invalid API Key (用户 access token 未找到，API Key 无效)"
            )

        if code == 10002:
            detail = body.get("data", {})
            raise AuthenticationError(
                f"Parameter validation error (入参校验错误): {detail}"
            )

        if code != 200:
            raise AuthenticationError(body.get("message", "Authentication failed (认证失败)"))

        # code == 200：认证成功
        data = body.get("data", {})

        # 缓存 token 信息
        self.access_token = data["apiToken"]
        # expireAtTime 是 13 位毫秒时间戳，转换为秒级时间戳
        expire_at_ms = data.get("expireAtTime", 0)
        self._expire_at = expire_at_ms / 1000.0 if expire_at_ms else None
        self._user_id = data.get("userId")

        logger.info(
            "Authentication successful (认证成功) (userId=%s, expireAt=%.0f)",
            self._user_id, self._expire_at or 0
        )
        return data

    def token_expired(self) -> bool:
        """判断 access_token 是否已过期（提前 60 秒刷新）。

        基于服务端返回的 expireAtTime 绝对时间戳判断。

        Returns:
            True 表示 token 已过期或即将过期，需要刷新。
        """
        if self.access_token is None:
            return True

        if self._expire_at is not None:
            return time.time() >= (self._expire_at - TOKEN_REFRESH_BUFFER)

        return True

    def refresh_token(self) -> dict:
        """使用 api_key 重新获取 access_token。

        内部直接再次调用 authenticate()，使用保存的 api_key
        向 POST /auth/token 发起新的认证请求。

        Returns:
            认证接口返回的 data 字典。

        Raises:
            AuthenticationError: 认证失败。
        """
        logger.info("Token expired, refreshing... (Token 已过期，正在刷新...)")
        return self.authenticate()

    def ensure_token_valid(self) -> None:
        """确保 access_token 有效，过期则自动刷新。

        在每次 API 请求前调用此方法，保证 token 的有效性。

        Raises:
            AuthenticationError: 刷新失败时抛出。
        """
        if self.token_expired():
            self.refresh_token()
    '''
    def get_auth_url(self) -> str:
        """获取认证接口的完整 URL。

        Returns:
            完整的认证接口 URL，如 "auth_url/user/api/tokens"。
        """
        return f"{self._base_url()}/user/api/tokens"
    '''

    @property
    def api_key(self) -> str:
        """返回脱敏后的 api_key（仅显示前 4 位 + 后 4 位）。

        用于日志输出，避免泄露完整 api_key。
        """
        if len(self._api_key) <= 8:
            return self._api_key[:2] + "***"
        return self._api_key[:4] + "***" + self._api_key[-4:]

    @property
    def connection_parameters(self) -> dict:
        """返回连接参数摘要（用于调试）。

        Returns:
            包含 base_url, api_key(脱敏), token 状态的字典。
        """
        return {
            "base_url": "<hidden>",
            "api_key": self.api_key,
            "channel": self.channel,
            "has_token": self.access_token is not None,
            "token_expired": self.token_expired(),
            "user_id": self._user_id,
            "expire_at": self._expire_at,
        }

    @staticmethod
    def _unwrap_response(response: requests.Response) -> dict:
        """统一拆包云平台 API 响应。

        云平台所有 API 均使用以下包装结构::

            {
                "requestTime": "...",
                "code": 0,           // 0=成功, 非0=业务错误
                "message": "...",
                "data": {...},
                "responseTime": "..."
            }

        Args:
            response: requests 响应对象。

        Returns:
            响应中的 data 字段内容。

        Raises:
            APIError: code != 0 或 HTTP 状态码异常时抛出。
        """
        try:
            body = response.json()
        except ValueError:
            raise APIError(
                message="API response parsing failed, non-JSON format (API 响应解析失败，非 JSON 格式)",
                status_code=response.status_code,
            )

        # 检查 HTTP 状态码
        if response.status_code != 200:
            raise APIError(
                message=body.get("message", "Unknown error"),
                status_code=response.status_code,
                response_body=body,
            )

        # 检查业务状态码
        code = body.get("code")
        if code != 200:
            raise APIError(
                message=body.get("message", "Unknown error"),
                status_code=response.status_code,
                response_body=body,
            )

        return body.get("data", {})


