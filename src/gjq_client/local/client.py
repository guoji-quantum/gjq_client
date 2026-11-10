"""本地 RuntimeClient 替身：在本机 CPU 上执行 FAS-LOCAL 任务，不访问云平台。"""

from __future__ import annotations

import secrets
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any

from qiskit import QuantumCircuit, qasm2
from qiskit.primitives import StatevectorSampler
from ..gjq_runtime.submit_payload import ensure_circuit_has_measure, validate_shots
from ..utils.exceptions import (
    GJQValidationError as ValueError,
    JobFailedError,
    JobNotFoundError,
)

LOCAL_BACKEND_NAME = "FAS-LOCAL"
LOCAL_MAX_QUBITS = 20
LOCAL_MAX_SHOTS = 100000
_MAX_SEED = 2**64 - 1


def resolve_seed(seed: Any) -> int:
    """返回用户指定的种子；未指定时随机生成一个，保证每次运行都可复现。"""
    if seed is None:
        return secrets.randbits(32)
    if type(seed) is not int or not 0 <= seed <= _MAX_SEED:
        raise ValueError(f"seed must be an integer in [0, {_MAX_SEED}]")
    return seed


def measurement_clbit_to_qubit(circuit: QuantumCircuit) -> dict[int, int]:
    """返回经典位 → 量子位的一一映射；重复测量或覆盖经典位时拒绝。"""
    measured_qubits: set[int] = set()
    clbit_to_qubit: dict[int, int] = {}
    for instruction in circuit.data:
        if instruction.operation.name != "measure":
            continue
        qubit = circuit.find_bit(instruction.qubits[0]).index
        clbit = circuit.find_bit(instruction.clbits[0]).index
        if qubit in measured_qubits or clbit in clbit_to_qubit:
            raise ValueError(
                f"{LOCAL_BACKEND_NAME} requires one-to-one measurements "
                "(不支持重复测量或覆盖经典位)"
            )
        measured_qubits.add(qubit)
        clbit_to_qubit[clbit] = qubit
    return clbit_to_qubit


def counts_in_qubit_order(
    circuit: QuantumCircuit, counts: dict[str, int]
) -> dict[str, int]:
    """将 StatevectorSampler 的经典位序 counts 重排为量子位序（与云端 FAS 一致）。

    输出位串右边是 q0，未测量的量子位记为 0；宽度为 ``circuit.num_qubits``。
    """
    clbit_to_qubit = measurement_clbit_to_qubit(circuit)
    num_qubits = circuit.num_qubits
    num_clbits = circuit.num_clbits
    reordered: dict[str, int] = {}
    for state, frequency in counts.items():
        if not isinstance(state, str) or type(frequency) is not int:
            raise JobFailedError("Invalid local measurement counts")
        bits = state.zfill(num_clbits)
        if len(bits) != num_clbits or any(bit not in "01" for bit in bits):
            raise JobFailedError("Invalid local measurement bitstring")
        qubit_values = ["0"] * num_qubits
        for clbit, bit in enumerate(reversed(bits)):
            qubit = clbit_to_qubit.get(clbit)
            if qubit is not None:
                qubit_values[qubit] = bit
        key = "".join(reversed(qubit_values))
        reordered[key] = reordered.get(key, 0) + frequency
    return reordered


def _reject_operations_after_measurement(circuit: QuantumCircuit) -> None:
    """拒绝 reset 和同一比特测量后的操作，保证一次构态后采样的语义正确。"""
    measured: set[int] = set()
    for instruction in circuit.data:
        name = instruction.operation.name
        if name == "reset":
            raise ValueError(
                f"{LOCAL_BACKEND_NAME} does not support reset "
                "(本地态矢量采样不支持重置操作)"
            )
        if name == "barrier":
            continue
        qubits = {circuit.find_bit(qubit).index for qubit in instruction.qubits}
        if measured & qubits:
            raise ValueError(
                f"{LOCAL_BACKEND_NAME} does not support operations after measurement on the "
                f"same qubit (FAS-LOCAL 不支持在同一比特测量后继续操作): '{name}' on "
                f"qubits {sorted(measured & qubits)}"
            )
        if name == "measure":
            measured |= qubits


class LocalRuntimeClient:
    """实现 Sampler、Estimator 和 RuntimeJob 用到的 RuntimeClient 方法。

    任务在 ``submit_task`` 中同步完成模拟，结果保存在内存里，
    因此 RuntimeJob 轮询时任务已经处于完成状态。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}

    def list_backends(self) -> list[dict]:
        return [{
            "name": LOCAL_BACKEND_NAME,
            "type": "Local CPU Simulator",
            "max_qubits": LOCAL_MAX_QUBITS,
            "available_qubits": LOCAL_MAX_QUBITS,
            "num_of_pending_tasks": 0,
            "job_mode": ["job"],
        }]

    def backend_properties(self, backend_name: str) -> None:
        return None

    def create_session(self, backend_name: str, max_time: int | None = None) -> dict:
        raise ValueError(
            f"Backend '{LOCAL_BACKEND_NAME}' does not support Session mode "
            "(本地模拟器不支持 Session 模式)"
        )

    def submit_task(self, payload: dict) -> dict:
        """从 payload 的 qasm2 还原线路并完成态矢量采样，返回本地任务 ID。"""
        if payload.get("device_name") != LOCAL_BACKEND_NAME:
            raise ValueError(
                f"local simulator only runs '{LOCAL_BACKEND_NAME}' tasks, "
                f"got device_name={payload.get('device_name')!r}"
            )
        for key, feature in (
            ("simulator_config", "simulator_config"),
            ("session_id", "Session mode"),
            ("amplitude-index", "amplitude-index"),
        ):
            if payload.get(key) is not None:
                raise ValueError(f"{LOCAL_BACKEND_NAME} does not support {feature}")
        shots = validate_shots(payload.get("repetitions"))
        if shots > LOCAL_MAX_SHOTS:
            raise ValueError(
                f"shots {shots} exceeds backend '{LOCAL_BACKEND_NAME}' limit {LOCAL_MAX_SHOTS}"
            )
        seed = resolve_seed(payload.get("seed"))

        qasm = payload.get("qasm2")
        if not isinstance(qasm, str) or not qasm:
            raise ValueError("payload is missing the qasm2 circuit")
        circuit = qasm2.loads(qasm, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
        if circuit.num_qubits > LOCAL_MAX_QUBITS:
            raise ValueError(
                f"circuit uses {circuit.num_qubits} qubits, but backend "
                f"'{LOCAL_BACKEND_NAME}' supports at most {LOCAL_MAX_QUBITS}"
            )
        ensure_circuit_has_measure(circuit)
        _reject_operations_after_measurement(circuit)

        started = time.perf_counter()
        try:
            pub_result = StatevectorSampler(seed=seed).run([circuit], shots=shots).result()[0]
            classical_counts = {
                state: int(frequency)
                for state, frequency in pub_result.join_data().get_counts().items()
            }
            counts = counts_in_qubit_order(circuit, classical_counts)
        except ValueError:
            raise
        except Exception as exc:
            raise JobFailedError(f"Local simulation failed (本地模拟失败): {exc}") from exc
        elapsed = time.perf_counter() - started

        states = sorted(counts)
        result = {
            "prob_his": [{"qState": state, "prob": counts[state] / shots} for state in states],
            "freq_res": [{"qState": state, "freq": counts[state]} for state in states],
            "seed": seed,
        }
        instance_id = f"local-{uuid.uuid4()}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log = "\n".join((
            f"{timestamp} backend: {LOCAL_BACKEND_NAME} (local statevector simulator)",
            f"{timestamp} circuit-type: {payload.get('circuit-type')}",
            f"{timestamp} qubits: {circuit.num_qubits}, shots: {shots}, seed: {seed}",
            f"{timestamp} simulation completed in {elapsed:.3f} s",
        ))
        self._tasks[instance_id] = {"result": result, "log": log}
        return {"instanceId": instance_id, "state": "completed"}

    def _task(self, instance_id: str) -> dict:
        task = self._tasks.get(instance_id)
        if task is None:
            raise JobNotFoundError(f"Task '{instance_id}' not found (任务 '{instance_id}' 不存在)")
        return task

    def task_status(self, instance_id: str) -> dict:
        self._task(instance_id)
        return {"instanceId": instance_id, "task_state": "completed", "error_code": 0}

    def task_result(self, instance_id: str) -> dict:
        return deepcopy(self._task(instance_id)["result"])

    def task_log(self, instance_id: str) -> dict:
        return {"instanceId": instance_id, "log": self._task(instance_id)["log"]}
