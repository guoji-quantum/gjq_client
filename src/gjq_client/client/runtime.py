"""
高层 REST API 客户端 (runtime.py)
===================================

RuntimeClient 是 SDK 与云端服务交互的核心客户端，提供业务导向的
方法接口。内部通过 REST 适配器层（UserToken / Backend / Task）
委托到 RetrySession 完成实际的 HTTP 通信。

架构::

    RuntimeClient (业务方法)
    ├── UserToken adapter  → RetrySession (auth_session)
    ├── Backend adapter    → RetrySession (backend_session)
    └── Task adapter       → RetrySession (backend_session)

使用示例::

    from gjq_client.client.client_parameters import ClientParameters
    from gjq_client.client.runtime import RuntimeClient

    params = ClientParameters(api_key="api_key")
    client = RuntimeClient(params)

    backends = client.list_backends()
    result = client.submit_task(payload)
"""

import logging
from typing import Optional, Any

from gjq_client.client.client_parameters import ClientParameters
from gjq_client.client.auth import Auth
from gjq_client.client.session import RetrySession
from gjq_client.client.rest.user_token import UserToken
from gjq_client.client.rest.backend import Backend
from gjq_client.client.rest.task import Task
from gjq_client.utils.exceptions import (
    APIError,
    BackendNotFoundError,
    JobNotFoundError,
)

__all__ = ["RuntimeClient"]

logger = logging.getLogger(__name__)


class RuntimeClient:
    """中心量子云平台 REST API 客户端。

    唯一与云端 REST API 通信的类，所有 API 调用都通过此类发出。
    内部使用分层适配器架构：

    - auth_session (RetrySession): 绑定认证服务 base_url，不注入 Auth
    - backend_session (RetrySession): 绑定后端服务 backend_url，注入 Auth

    Args:
        client_params: 客户端连接参数管理器（含 api_key 和 token 管理）。
        max_retries: HTTP 请求最大重试次数，默认 3。
        timeout: 单次请求超时（秒），默认 30。
    """

    def __init__(
        self,
        client_params: ClientParameters,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        self._client_params = client_params
        self._auth = Auth(client_params)

        # 认证服务 session（不注入 Auth，登录时尚无 token）
        self._auth_session = RetrySession(
            base_url=client_params.base_url,
            auth=None,
            max_retries=max_retries,
            timeout=timeout,
        )

        # 后端服务 session（注入 Auth，自动管理 Bearer token）
        self._backend_session = RetrySession(
            base_url=client_params.backend_url,
            auth=self._auth,
            max_retries=max_retries,
            timeout=timeout,
        )

        # 初始化 REST 适配器
        self._user_token = UserToken(self._auth_session)
        self._backend = Backend(self._backend_session)
        self._task = Task(self._backend_session)

        # 首次初始化时自动认证
        self._client_params.authenticate()

    # ==========================================================================
    # 后端信息查询
    # ==========================================================================

    def list_backends(self) -> list[dict]:
        """获取所有可用量子后端列表。

        GET {backend_url}/v1/guojisdk/getAvailableMachines

        Returns:
            后端信息字典列表，每个字典包含:
                - name (str): 后端名称
                - max_qubits (int): 最大量子比特数
                - available_qubits (int): 可用量子比特数
                - num_of_pending_tasks (int): 当前排队任务数

        Raises:
            APIError: API 调用失败。
        """
        response = self._backend.list_backends()
        return self._unwrap_backend(response)

    def backend_configuration(self, backend_name: str) -> dict:
        """获取指定后端的静态配置信息。

        GET {backend_url}/v1/guojisdk/getMachineConfig/{backend_name}

        Args:
            backend_name: 后端名称。

        Returns:
            后端配置字典，包含 basis_gates, coupling_map,
            n_qubits, max_shots, gate_error, T1, T2 等字段。

        Raises:
            BackendNotFoundError: 后端不存在。
            APIError: API 调用失败。
        """
        try:
            machine = self._backend.machine_backend(backend_name)
            response = machine.configuration()
            return self._unwrap_backend(response)
        except APIError as e:
            if e.status_code == 404:
                raise BackendNotFoundError(
                    f"Backend '{backend_name}' not found (后端 '{backend_name}' 不存在)"
                ) from e
            raise

    def backend_properties(self, backend_name: str) -> Optional[dict]:
        """获取指定后端的校准信息（T1/T2/门保真度等）。

        GET {backend_url}/v1/guojisdk/getMachineProperties/{backend_name}

        Args:
            backend_name: 后端名称。

        Returns:
            校准数据字典，包含 qubits, gates, last_update_date 等。
            可能为 None（后端不提供校准数据时）。

        Raises:
            BackendNotFoundError: 后端不存在。
            APIError: API 调用失败。
        """
        try:
            machine = self._backend.machine_backend(backend_name)
            response = machine.properties()
            return self._unwrap_backend(response)
        except APIError as e:
            if e.status_code == 404:
                raise BackendNotFoundError(
                    f"Backend '{backend_name}' not found (后端 '{backend_name}' 不存在)"
                ) from e
            raise

    # ==========================================================================
    # 任务管理
    # ==========================================================================

    def submit_task(self, payload: dict) -> dict:
        """提交量子计算任务。

        POST {backend_url}/v1/guojisdk/submitTask

        Args:
            payload: 任务提交数据，包含 device_name, quantum-num,
                     repetitions, steps 等字段。

        Returns:
            提交结果字典，包含:
                - instanceId (str): 任务实例 ID
                - state (str): 初始状态，通常为 "pending"

        Raises:
            APIError: 提交失败。
        """
        response = self._task.submit(payload)
        return self._unwrap_backend(response)

    def task_status(self, instance_id: str) -> dict:
        """查询任务状态。

        GET {backend_url}/v1/guojisdk/getTaskState/{instanceId}

        状态值: pending, running, failed, completed

        Args:
            instance_id: 任务实例 ID（submitTask 返回的 instanceId）。

        Returns:
            状态字典，包含:
                - instanceId (str): 任务实例 ID
                - task_state (str): 任务状态
                - error_code (int): 0 表示成功，否则为 HTTP 状态码
        """
        instance = self._task.task_instance(instance_id)
        response = instance.status()

        if response.status_code == 200:
            data = self._unwrap_backend(response)
            data["error_code"] = 0
            return data
        else:
            return {
                "instanceId": instance_id,
                "task_state": "error",
                "error_code": response.status_code,
            }

    def task_result(self, instance_id: str) -> dict:
        """获取任务执行结果。

        GET {backend_url}/v1/guojisdk/getTaskResult/{instanceId}

        Args:
            instance_id: 任务实例 ID。

        Returns:
            结果字典，包含任务执行结果数据。

        Raises:
            JobNotFoundError: 任务不存在。
            APIError: API 调用失败。
        """
        try:
            instance = self._task.task_instance(instance_id)
            response = instance.result()
            return self._unwrap_backend(response)
        except APIError as e:
            if e.status_code == 404:
                raise JobNotFoundError(
                    f"Task '{instance_id}' not found (任务 '{instance_id}' 不存在)"
                ) from e
            raise

    def task_detail(self, instance_id: str) -> dict:
        """获取任务详细信息。

        GET {backend_url}/v1/guojisdk/getTaskDetail/{instanceId}

        Args:
            instance_id: 任务实例 ID。

        Returns:
            任务详情字典，包含:
                - backend_name (str): 后端名称
                - shots (int): 测量次数
                - instanceId (str): 任务实例 ID
                - submit_time (str): 提交时间
        """
        instance = self._task.task_instance(instance_id)
        response = instance.detail()
        return self._unwrap_backend(response)

    def task_log(self, instance_id: str) -> dict:
        """获取任务执行日志。

        GET {backend_url}/v1/guojisdk/getTaskLog/{instanceId}

        Args:
            instance_id: 任务实例 ID。

        Returns:
            日志字典，包含:
                - instanceId (str): 任务实例 ID
                - log (str): 日志文本
        """
        instance = self._task.task_instance(instance_id)
        response = instance.log()
        return self._unwrap_backend(response)

    def task_list(self) -> list[dict]:
        """获取当前用户的任务状态列表。

        GET {backend_url}/v1/guojisdk/getTaskList

        Returns:
            任务状态字典列表，每项包含:
                - instanceId (str): 任务实例 ID
                - task_state (str): 任务状态
        """
        response = self._task.list_tasks()
        return self._unwrap_backend(response)

    # ==========================================================================
    # 响应拆包
    # ==========================================================================

    @staticmethod
    def _unwrap(response: "requests.Response") -> Any:
        """拆包认证服务 API 响应（message 字段格式）。

        Args:
            response: HTTP 响应对象。

        Returns:
            响应中的 data 字段值。

        Raises:
            APIError: code != 200 或 HTTP 错误。
        """
        return ClientParameters._unwrap_response(response)

    @staticmethod
    def _unwrap_backend(response: "requests.Response") -> Any:
        """拆包后端查询 API 响应（msg 字段格式）。

        后端查询 API 响应结构::

            {
                "data": [...],
                "msg": "success!",
                "code": 200
            }

        Args:
            response: HTTP 响应对象。

        Returns:
            响应中的 data 字段值。

        Raises:
            APIError: code != 200 或 HTTP 错误。
        """
        try:
            body = response.json()
        except ValueError:
            raise APIError(
                message="API response parsing failed, non-JSON format (API 响应解析失败，非 JSON 格式)",
                status_code=response.status_code,
            )

        if response.status_code != 200:
            raise APIError(
                message=body.get("msg", "Unknown error"),
                status_code=response.status_code,
                response_body=body,
            )

        code = body.get("code")
        if code != 200:
            raise APIError(
                message=body.get("msg", "Unknown error"),
                status_code=response.status_code,
                response_body=body,
            )

        return body.get("data", {})

    # ==========================================================================
    # 生命周期
    # ==========================================================================

    def close(self) -> None:
        """关闭客户端，释放连接资源。"""
        self._auth_session.close()
        self._backend_session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
