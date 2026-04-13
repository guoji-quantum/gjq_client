"""
量子后端查询适配器 (backend.py)
================================

封装后端查询服务上的后端信息 API:
    - Backend: 根适配器，管理后端列表和工厂方法
    - MachineBackend: 子资源适配器，管理单个后端的配置和校准信息

使用示例::

    session = RetrySession(base_url="backend_url", auth=auth)
    backend_api = Backend(session)

    # 列出所有后端
    response = backend_api.list_backends()

    # 获取单个后端的配置
    machine = backend_api.machine_backend("Baihua")
    config_resp = machine.configuration()
    props_resp = machine.properties()
"""

import requests

from gjq_client.client.rest.base import RestAdapterBase

__all__ = ["Backend", "MachineBackend"]


class Backend(RestAdapterBase):
    """量子后端根适配器。

    管理后端列表查询和 MachineBackend 子适配器的创建。

    URL_MAP:
        list -> /v1/guojisdk/getAvailableMachines
    """

    URL_MAP = {
        "list": "/v1/guojisdk/getAvailableMachines",
    }

    def list_backends(self) -> requests.Response:
        """获取所有可用量子后端列表。

        GET /v1/guojisdk/getAvailableMachines

        Returns:
            原始 requests.Response 对象。
        """
        url = self.get_url("list")
        return self.session.request("GET", url)

    def machine_backend(self, backend_name: str) -> "MachineBackend":
        """创建指定后端的子资源适配器。

        Args:
            backend_name: 后端名称（如 "Baihua", "Guoji01"）。

        Returns:
            MachineBackend 子适配器实例。
        """
        return MachineBackend(self.session, backend_name)


class MachineBackend(RestAdapterBase):
    """单个量子后端子资源适配器。

    封装特定后端实例的配置和校准信息查询接口。

    URL_MAP:
        config     -> /v1/guojisdk/getMachineConfig
        properties -> /v1/guojisdk/getMachineProperties
    """

    URL_MAP = {
        "config": "/v1/guojisdk/getMachineConfig",
        "properties": "/v1/guojisdk/getMachineProperties",
    }

    def __init__(self, session, backend_name: str):
        super().__init__(session)
        self._backend_name = backend_name

    def configuration(self) -> requests.Response:
        """获取后端静态配置信息。

        GET /v1/guojisdk/getMachineConfig/{backend_name}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['config']}/{self._backend_name}"
        return self.session.request("GET", url)

    def properties(self) -> requests.Response:
        """获取后端校准信息（T1/T2/门保真度等）。

        GET /v1/guojisdk/getMachineProperties/{backend_name}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['properties']}/{self._backend_name}"
        return self.session.request("GET", url)
