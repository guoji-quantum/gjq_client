"""
用户 Token 认证适配器 (user_token.py)
=====================================

封装认证服务上的 /user/api/tokens 登录接口。

此适配器使用**不带 Auth 注入**的 RetrySession（认证服务），
因为登录时尚无 JWT token。

使用示例::

    session = RetrySession(base_url="auth_url")
    user_token = UserToken(session)
    response = user_token.login("api_key")
"""

import requests

from gjq_client.client.rest.base import RestAdapterBase

__all__ = ["UserToken"]


class UserToken(RestAdapterBase):
    """用户 Token 认证适配器。

    封装 POST /user/api/tokens 登录接口。

    URL_MAP:
        tokens -> /user/api/tokens
    """

    URL_MAP = {
        "tokens": "/user/api/tokens",
    }

    def login(self, api_key: str) -> requests.Response:
        """使用 API_KEY 获取用户 access token。

        POST /user/api/tokens
        Body: {"accessToken": "<api_key>"}

        Args:
            api_key: 用户的 API Key。

        Returns:
            原始 requests.Response 对象，调用方负责拆包。
        """
        url = self.get_url("tokens")
        return self.session.request(
            "POST",
            url,
            json={"accessToken": api_key},
        )
