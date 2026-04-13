"""
HTTP 认证模块 (auth.py)
=======================

职责:
    - 从 ClientParameters 获取当前有效的 JWT access_token
    - 生成 API 请求所需的 Authorization: Bearer Header
    - 在 token 过期时自动触发刷新
    - **不负责** Token 的获取或管理（由 ClientParameters 负责）

使用示例::

    auth = Auth(client_params)
    headers = auth.get_headers()
    # {'Authorization': 'Bearer eyJhbGci...', 'Content-Type': 'application/json'}

    response = requests.get(url, headers=headers)
"""

from gjq_client.client.client_parameters import ClientParameters

__all__ = ["Auth"]


class Auth:
    """HTTP请求认证处理器。

    负责为每次API请求生成包含JWT access_token的HTTP Header。
    在每次生成Header前会自动检查token是否过期，过期则触发刷新。

    Args:
        client_params: ClientParameters 实例，提供 token 管理能力。
    """

    def __init__(self, client_params: ClientParameters):
        self._client_params = client_params

    def get_headers(self) -> dict[str, str]:
        """生成带认证信息的 HTTP 请求头。

        每次调用时自动检查 token 有效性，过期则触发刷新。

        返回的 Header 包含:
            - Authorization: Bearer {JWT}  — 云平台标准认证格式
            - Content-Type: application/json

        Returns:
            HTTP 请求头字典。

        Raises:
            AuthenticationError: token 刷新失败时抛出。
        """
        # 确保 token 有效
        self._client_params.ensure_token_valid()

        return {
            "Authorization": f"Bearer {self._client_params.access_token}",
            "Content-Type": "application/json",
        }

    @property
    def token(self) -> str | None:
        """获取当前 access_token（不触发刷新）。

        Returns:
            当前缓存的 JWT token 字符串，未认证时返回 None。
        """
        return self._client_params.access_token
