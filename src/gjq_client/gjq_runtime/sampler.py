"""Sampler类, 用来提交任务, 返回一个RuntimeJob类."""

from __future__ import annotations

from ..backend.gjq_backend import GJQBackend
from qiskit import QuantumCircuit
from qiskit.qasm2 import dumps
from .runtime_job import RuntimeJob
from .session import Session
from .submit_payload import (
    build_submit_payload,
    ensure_circuit_has_measure,
    ensure_run_fits_backend,
)
from ..utils.utils import circuit_to_json_layers
from ..utils.exceptions import GJQValidationError as ValueError, JobFailedError


class Sampler():
    """Runtime Sampler交互类。提交任务, 返回一个RuntimeJob。"""

    def __init__(
        self,
        backend: GJQBackend | None = None,
        options: dict | None = None,
        mode: Session | None = None,
        amplitude_index: list[int] | None = None,
    ):
        if mode is not None:
            if not isinstance(mode, Session):
                raise ValueError("mode must be a Session")
            backend = mode.backend
        if backend is None:
            raise ValueError("backend is required")

        self._backend = backend
        self._options = options
        self._session_id = mode.session_id if mode is not None else None
        self._amplitude_index = amplitude_index

    def run(
        self,
        circuit: QuantumCircuit,
        shots: int | None = 1024,
        amplitude_index: list[int] | None = None,
    ) -> RuntimeJob:
        run_amplitude_index = (
            amplitude_index if amplitude_index is not None else self._amplitude_index
        )
        if not isinstance(circuit, QuantumCircuit):
            raise ValueError("circuit must be a QuantumCircuit")
        ensure_run_fits_backend(circuit, shots, self._backend)
        if self._backend.name == "MPS" and shots == 0:
            raise ValueError("MPS Sampler requires positive integer shots")
        ensure_circuit_has_measure(circuit)
        instructions = circuit_to_json_layers(
            circuit,
            supported_operations=getattr(self._backend, "operation_names", ()),
        )
        if self._backend.name == "MPS":
            # Idle qubits remain part of the user's declared circuit.
            instructions["quantum-num"] = circuit.num_qubits
        tasks = build_submit_payload(
            backend_name=self._backend.name,
            shots=shots,
            instructions=instructions,
            circuit_type="sampler",
            qasm2=dumps(circuit),
            options=self._options,
            session_id=self._session_id,
            amplitude_index=run_amplitude_index,
        )

        response = self._backend._api_client.submit_task(tasks)
        job_id = response.get("instanceId")
        if job_id is None:
            raise JobFailedError("Task submission failed (提交任务失败)")
        print(f"Task submitted successfully (提交任务成功), Task ID: {job_id}")
        return RuntimeJob(
            self._backend._api_client,
            job_id,
            backend_name=self._backend.name,
            shots=shots,
            circuit_type="sampler",
            num_qubits=circuit.num_qubits,
        )
