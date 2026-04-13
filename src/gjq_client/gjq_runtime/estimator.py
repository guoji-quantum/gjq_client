



"""Estimator类, 用来提交任务, 返回一个RuntimeJob类."""

from __future__ import annotations


import logging


from ..backend.gjq_backend import GJQBackend
from qiskit import QuantumCircuit
from .runtime_job import RuntimeJob
from ..utils.utils import circuit_to_json_layers
from qiskit.quantum_info import SparsePauliOp

logger = logging.getLogger(__name__)


class Estimator():
    """Runtime Estimator交互类。
    提交任务, 返回一个RuntimeJob
    """

    def __init__(
        self,
        backend: GJQBackend,
        options: dict | None = None,
    ):
        """初始化Estimator类.

        Args:
            backend: 运行时的后端
            options: 运行时的选项
        """
        self._backend = backend
        self._options = options

    def run(self, circuit:QuantumCircuit, shots: int | None = 1024,obs: SparsePauliOp | None = None) -> RuntimeJob:
        """
            提交一个请求给 Estimator 服务。

            Args:
                circuits: QuantumCircuit对象。
                shots: 测量次数，默认为1024。
                obs: SparsePauliOp对象，用于计算期望值。
            Returns:
                RuntimeJob类
        """
        if not isinstance(circuit, QuantumCircuit):
            raise ValueError("circuit must be a QuantumCircuit")
        instructions = circuit_to_json_layers(circuit)
    
        tasks={"device_name":self._backend.name,"repetitions":shots,"quantum-num":instructions.get('quantum-num'),"steps":instructions.get('steps')}

        response=self._backend._api_client.submit_task(tasks)
        job_id=response.get('instanceId')
        if job_id is None:
            raise RuntimeError("Task submission failed (提交任务失败)")
        print(f"Task submitted successfully (提交任务成功), Task ID: {job_id}")
        return RuntimeJob(self._backend._api_client, job_id, obs) 


