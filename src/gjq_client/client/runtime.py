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

import requests

from gjq_client.client.client_parameters import ClientParameters
from gjq_client.client.auth import Auth
from gjq_client.client.session import RetrySession
from gjq_client.client.rest.user_token import UserToken
from gjq_client.client.rest.backend import Backend
from gjq_client.client.rest.task import Task
from gjq_client.utils.exceptions import (
    APIError,
    BackendNotFoundError,
    BackendOfflineError,
    JobNotFoundError,
)
from .backend_url_config import decrypt_url,DEFAULT_BACKEND_URL,DEFAULT_BASE_URL

__all__ = ["RuntimeClient"]

logger = logging.getLogger(__name__)

# 模拟器后端提交任务时需要 payload 中包含 measure-position 字段。
SIMULATOR_BACKEND_NAMES = ["FAS-CPU", "SAS-CPU", "SAS-GPU"]
AMPLITUDE_INDEX_REQUIRED_BACKEND_NAMES = ["SAS-CPU", "SAS-GPU"]
_SIMULATOR_BASIS_GATES = [
    "x",
    "y",
    "z",
    "s",
    "sdg",
    "t",
    "tdg",
    "h",
    "rx",
    "ry",
    "rz",
    "swap",
    "iswap",
    "cp",
    "cx",
    "cz",
    "ccx",
    "cswap",
    "rxx",
    "ryy",
    "rzz",
    "measure",
]


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
            base_url=client_params._base_override or decrypt_url(b'Ry8h9VgUXWpCCKQwcbEB8w==',DEFAULT_BASE_URL),
            auth=None,
            max_retries=max_retries,
            timeout=timeout,
        )

        # 后端服务 session（注入 Auth，自动管理 Bearer token）
        self._backend_session = RetrySession(
            base_url=client_params._backend_override or decrypt_url(b'Ry8h9VgUXWpCCKQwcbEB8w==',DEFAULT_BACKEND_URL),
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
            if self._api_error_code(e) == 1011:
                simulator_summary = self._get_available_backend(backend_name)
                if simulator_summary and self._is_simulator_backend(simulator_summary):
                    return self._build_simulator_configuration(simulator_summary)
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
            if self._api_error_code(e) == 1011:
                simulator_summary = self._get_available_backend(backend_name)
                if simulator_summary and self._is_simulator_backend(simulator_summary):
                    return self._build_simulator_properties(simulator_summary)
            if e.status_code == 404:
                raise BackendNotFoundError(
                    f"Backend '{backend_name}' not found (后端 '{backend_name}' 不存在)"
                ) from e
            raise

    # ==========================================================================
    # 任务管理
    # ==========================================================================

    def submit_task(self, payload: dict) -> dict:
        """提交量子计算任务（提交前自动检测目标后端可用性）。

        提交流程:
            1. 从 payload 中提取 device_name
            2. 查询当前可用后端列表
            3. 如果所有后端均处于维护状态，拒绝提交并给出说明
            4. 如果目标后端不在可用列表中，拒绝提交并列出可用后端
            5. 目标后端可用，正常提交

        POST {backend_url}/v1/guojisdk/submitTask

        Args:
            payload: 任务提交数据，包含 device_name, quantum-num,
                     repetitions, steps 等字段。

        Returns:
            提交结果字典，包含:
                - instanceId (str): 任务实例 ID
                - state (str): 初始状态，通常为 "pending"

        Raises:
            APIError: payload 缺少 device_name 或提交失败。
            BackendOfflineError: 目标后端不可用或所有后端维护中。
        """
        # --- 前置校验：提取目标后端名称 ---
        device_name = payload.get("device_name")
        if not device_name:
            raise APIError(
                message="Missing 'device_name' in payload (payload 缺少 'device_name' 字段)"
            )

        # --- 前置校验：查询可用后端列表 ---
        available = self.list_backends()
        available_by_name = {b["name"]: b for b in available}
        available_names = list(available_by_name)

        # 全维护场景
        if not available:
            raise BackendOfflineError(
                "All backends are currently under maintenance, task cannot be submitted. "
                "Please try again later. "
                "(所有后端当前均处于维护状态，无法提交任务。请稍后重试。)"
            )

        # 目标后端不可用
        if device_name not in available_names:
            raise BackendOfflineError(
                f"Backend '{device_name}' is currently unavailable. "
                f"Available backends: {available_names}. "
                f"(后端 '{device_name}' 当前不可用。可用后端: {available_names})"
            )

        # --- 模拟器后端：通过可用性检查后校验模拟器必需字段 ---
        target_backend = available_by_name[device_name]
        if self._is_simulator_backend(target_backend):
            if (
                device_name in AMPLITUDE_INDEX_REQUIRED_BACKEND_NAMES
                and "amplitude-index" not in payload
            ):
                raise APIError(
                    message=(
                        f"Backend '{device_name}' requires 'amplitude-index' in payload. "
                        "Pass it from the upper layer, for example "
                        "Sampler(..., amplitude_index=[0]). "
                    )
                )
            logger.info(
                "Simulator backend '%s' is available, submitting with measure-position=%s "
                "(模拟器后端 '%s' 可用，提交 measure-position=%s)",
                device_name, payload.get("measure-position"), device_name,
                payload.get("measure-position"),
            )

        # --- 正常提交 ---
        logger.info(
            "Backend '%s' is available, submitting task... "
            "(后端 '%s' 可用，正在提交任务...)",
            device_name, device_name,
        )
        response = self._task.submit(payload)
        return self._unwrap_backend(response)

    def _get_available_backend(self, backend_name: str) -> Optional[dict]:
        """从 getAvailableMachines 返回中查找指定后端摘要。"""
        for backend in self.list_backends():
            if backend.get("name") == backend_name:
                return backend
        return None

    @staticmethod
    def _is_simulator_backend(backend: dict) -> bool:
        """根据接口摘要判断后端是否为模拟器。"""
        backend_name = backend.get("name")
        backend_type = str(backend.get("type", "")).lower()
        return (
            backend_name in SIMULATOR_BACKEND_NAMES
            or "simulator" in backend_type
        )

    @staticmethod
    def _api_error_code(error: APIError) -> Optional[int]:
        """读取业务响应码；旧模拟器配置/属性接口会以 HTTP 200 返回 code=1011。"""
        if isinstance(error.response_body, dict):
            return error.response_body.get("code")
        return None

    @staticmethod
    def _build_simulator_configuration(summary: dict) -> dict:
        """按文档示例格式构造模拟器配置 data。"""
        backend_name = summary["name"]
        n_qubits = int(summary.get("max_qubits") or summary.get("available_qubits") or 1)
        description = f"{n_qubits} qubit simulator"
        if backend_name == "FAS-CPU":
            description = f"{n_qubits} qubit full-state CPU simulator"
        return {
            "basis_gates": list(_SIMULATOR_BASIS_GATES),
            "backend_name": backend_name,
            "backend_version": "0.1",
            "allow_q_object": True,
            "clops": None,
            "clops_h": None,
            "clops_v": None,
            "conditional": False,
            "coupling_map": [],
            "credits_required": False,
            "default_rep_delay": 0,
            "description": description,
            "dt": 4,
            "dtm": 4,
            "dynamic_reprate_enabled": False,
            "online_date": "2026-04-28T14:40:38Z",
            "supported_instructions": [],
            "gates": [],
            "instruction_signatures": [],
            "local": False,
            "max_experiments": 300,
            "max_shots": 100000,
            "meas_map": [],
            "measure_esp_enabled": False,
            "memory": True,
            "n_qubits": n_qubits,
            "n_registers": 1,
            "open_pulse": False,
            "parallel_compilation": False,
            "processor_type": {},
            "quantum_volume": None,
            "rep_delay_range": [0, 2000],
            "sample_name": {},
            "simulator": True,
            "supported_features": [],
            "timing_constraints": {},
        }

    @staticmethod
    def _build_simulator_properties(summary: dict) -> dict:
        """按文档示例格式构造模拟器属性 data。"""
        return {
            "backend_name": summary["name"],
            "backend_version": "0.1",
            "last_update_date": "2026-04-28T14:40:38Z",
            "general": [],
            "general_qlists": [],
            "qubits": [],
            "gates": [],
        }

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
            error_code = data.get("error_code", data.get("errorCode"))
            if data.get("task_state") == "failed" and not error_code:
                error_code = 1
            data["error_code"] = 0 if error_code is None else error_code
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
