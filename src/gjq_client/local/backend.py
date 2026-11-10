"""FAS-LOCAL：在本机 CPU 上运行的全振幅态矢量模拟器后端。"""

from __future__ import annotations

from ..backend.gjq_backend import GJQBackend
from ..client.runtime import RuntimeClient
from ..utils.backend_decoder import configuration_from_server_data
from .client import LOCAL_BACKEND_NAME, LOCAL_MAX_QUBITS, LocalRuntimeClient


class LocalSimulator(GJQBackend):
    """本地全振幅态矢量模拟器（FAS-LOCAL），无需 API Key，也不访问云平台。

    与云端 FAS-CPU 使用相同的门集、比特上限（20）和 shots 上限（100000），
    可以直接替换 Sampler、Estimator 和 PennyLane 设备中的 backend。
    通过 ``options={"seed": ...}`` 固定采样种子；未指定时自动生成，
    实际使用的种子记录在结果的 ``seed`` 字段中。
    不支持 reset；Estimator 仅支持可从末端 I/Z 测量计数计算的期望值。
    """

    def __init__(self) -> None:
        raw_config = RuntimeClient._build_simulator_configuration(
            {"name": LOCAL_BACKEND_NAME, "max_qubits": LOCAL_MAX_QUBITS}
        )
        raw_config["description"] = (
            f"{LOCAL_MAX_QUBITS} qubit full-state local CPU simulator "
            f"({LOCAL_MAX_QUBITS} 比特本地 CPU 全振幅态矢量模拟器)"
        )
        raw_config["local"] = True
        super().__init__(
            configuration=configuration_from_server_data(raw_config),
            service=None,
            api_client=LocalRuntimeClient(),
        )
