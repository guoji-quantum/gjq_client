"""
REST 适配器基类 (base.py)
=========================

所有 REST 适配器的基类，提供:
    - Session 注入：共享同一个 RetrySession 实例
    - URL_MAP 映射：将端点标识符映射到 URL 路径
    - get_url(key) 方法：拼接 prefix_url 和 URL_MAP 中的路径

使用示例::

    class MyAdapter(RestAdapterBase):
        URL_MAP = {
            "list": "/v1/items",
            "detail": "/v1/items/{id}",
        }

    adapter = MyAdapter(session, prefix_url="/api")
    url = adapter.get_url("list")  # => "/api/v1/items"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gjq_client.client.session import RetrySession

__all__ = ["RestAdapterBase"]


class RestAdapterBase:
    """REST 适配器基类。

    提供 URL_MAP 端点映射和 session 注入机制。子类通过定义
    URL_MAP 类属性来声明所管理的 API 端点，通过 get_url(key)
    获取拼接了 prefix_url 的完整相对路径。

    Args:
        session: RetrySession 实例，已绑定 base_url。
        prefix_url: URL 前缀，用于子资源适配器。默认为空字符串。
    """

    URL_MAP: dict[str, str] = {}

    def __init__(self, session: "RetrySession", prefix_url: str = ""):
        self.session = session
        self.prefix_url = prefix_url

    def get_url(self, key: str) -> str:
        """通过 URL_MAP 获取完整的相对路径。

        Args:
            key: URL_MAP 中的端点标识符。

        Returns:
            拼接 prefix_url 后的完整相对路径。

        Raises:
            KeyError: key 不在 URL_MAP 中。
        """
        return f"{self.prefix_url}{self.URL_MAP[key]}"
