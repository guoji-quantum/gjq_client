"""Estimator类, 用来提交任务, 返回一个RuntimeJob类."""

from __future__ import annotations

from copy import deepcopy

from ..backend.gjq_backend import GJQBackend
from qiskit import QuantumCircuit
from qiskit.qasm2 import dumps
from qiskit.quantum_info import Pauli, SparsePauliOp
from .runtime_job import RuntimeJob
from .session import Session
from .guoji_estimator import prepare_guoji_measurements
from .submit_payload import (
    build_submit_payload,
    ensure_circuit_has_measure,
    ensure_observables_are_measured,
    ensure_run_fits_backend,
    sparsepauliop_to_mps_observables,
    sparsepauliop_to_observables,
    validate_observables,
    validate_z_basis_observables,
)
from ..utils.utils import circuit_to_json_layers
from ..utils.exceptions import GJQValidationError as ValueError, JobFailedError


def _as_z_basis_observable(observable: SparsePauliOp) -> SparsePauliOp:
    """Represent a Pauli observable after the caller has diagonalized its circuit."""
    translation = str.maketrans({"X": "Z", "Y": "Z"})
    return SparsePauliOp.from_list([
        (label.translate(translation), coefficient)
        for label, coefficient in observable.to_list()
    ])


def _uses_client_side_expectation_values(backend: GJQBackend) -> bool:
    """Return whether this backend derives expectations from returned counts."""
    simulator = getattr(backend.configuration(), "simulator", None)
    if type(simulator) is bool:
        return simulator and backend.name != "MPS"
    return backend.name in {"FAS-CPU", "FAS-GPU", "SAS-CPU", "SAS-GPU"}


def _apply_transpiled_layout(
    circuit: QuantumCircuit,
    observable: SparsePauliOp,
) -> SparsePauliOp:
    """Map a logical observable onto the final physical layout of a circuit."""
    layout = getattr(circuit, "layout", None)
    final_index_layout = getattr(layout, "final_index_layout", None)
    if not callable(final_index_layout):
        return observable
    mapping = final_index_layout()
    if not mapping or observable.num_qubits > len(mapping):
        # A wider operator is already expressed in the output circuit space.
        return observable
    logical_width = len(mapping)
    expanded = SparsePauliOp.from_list([
        ("I" * (logical_width - len(label)) + label, coefficient)
        for label, coefficient in observable.to_list()
    ])
    return expanded.apply_layout(mapping, num_qubits=circuit.num_qubits)


class Estimator():
    """Runtime Estimator交互类。提交任务, 返回一个RuntimeJob。

    MPS 模拟器通过 options['simulator_config'] 传入：
    preset 为 fast/balanced/accurate 时只需 runtime.num_gpus；
    preset 为 expert 时还需 dtype、mps、svd（gesvdj 另需 tol/max_sweeps）。
    run(observable=...) 支持 Pauli 输入，或由 name、terms 组成的观测量列表；
    MPS 支持有限实数系数、多比特 Pauli 和具名 Pauli 求和。
    多项 SparsePauliOp 作为一个名为 observable 的整体算符提交；
    需要多个独立结果时使用具名观测量列表。
    MPS 直接从模拟状态计算期望值，无需 measure 门，也不要求观测比特被测量。
    Guoji08 使用相同的具名求和结果语义，并自动规范末端测量；真机要求正数 shots。
    """

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
        observable: SparsePauliOp | Pauli | str | list[dict] | None = None,
        amplitude_index: list[int] | None = None,
        _result_observable: SparsePauliOp | None = None,
        _basis_rotated: bool = False,
    ) -> RuntimeJob:
        run_amplitude_index = (
            amplitude_index if amplitude_index is not None else self._amplitude_index
        )
        if not isinstance(circuit, QuantumCircuit):
            raise ValueError("circuit must be a QuantumCircuit")
        ensure_run_fits_backend(circuit, shots, self._backend)
        if observable is None:
            raise ValueError("observable is required for Estimator")
        physical_observable = isinstance(observable, str)
        if not isinstance(observable, (SparsePauliOp, list)):
            try:
                observable = SparsePauliOp(observable)
            except Exception as exc:
                raise ValueError(
                    "observable must be a SparsePauliOp, Pauli, Pauli string, or named list"
                ) from exc
        if isinstance(observable, SparsePauliOp) and observable.num_qubits > circuit.num_qubits:
            raise ValueError("observable width must not exceed circuit width")
        if isinstance(observable, SparsePauliOp) and not _basis_rotated and not physical_observable:
            observable = _apply_transpiled_layout(circuit, observable)
        if _basis_rotated:
            if self._backend.name == "MPS" or not isinstance(observable, SparsePauliOp):
                raise ValueError("basis-rotated execution requires a non-MPS Pauli observable")
            # The private PennyLane path has already diagonalized X/Y measurements.
            # Submit and evaluate the equivalent Z-support operator so direct SDK
            # calls cannot use this path to reinterpret unrotated Z-basis counts.
            result_observable = (
                _result_observable if _result_observable is not None else observable
            )
            observable = _as_z_basis_observable(observable)
            _result_observable = _as_z_basis_observable(result_observable)
        if isinstance(observable, list):
            observables = deepcopy(observable) if self._backend.name == "Guoji08" else observable
        elif self._backend.name in {"MPS", "Guoji08"}:
            observables = sparsepauliop_to_mps_observables(observable)
        else:
            observables = sparsepauliop_to_observables(observable)
        validate_observables(observables, circuit.num_qubits)
        if self._backend.name == "Guoji08":
            circuit = prepare_guoji_measurements(circuit, observables)
        if self._backend.name != "MPS":
            ensure_circuit_has_measure(circuit)
            if _uses_client_side_expectation_values(self._backend):
                validate_z_basis_observables(observables)
            if self._backend.name != "Guoji08":
                ensure_observables_are_measured(circuit, observables)
        instructions = circuit_to_json_layers(
            circuit,
            supported_operations=getattr(self._backend, "operation_names", ()),
        )
        if self._backend.name == "MPS":
            # Idle qubits remain part of the user's declared circuit.
            instructions["quantum-num"] = circuit.num_qubits
        observable_qubits = {
            q
            for obs in observables
            for term in obs["terms"]
            for q in term["qubits"]
        }
        instructions["quantum-num"] = max(
            instructions["quantum-num"],
            max(observable_qubits, default=-1) + 1,
        )
        tasks = build_submit_payload(
            backend_name=self._backend.name,
            shots=shots,
            instructions=instructions,
            circuit_type="estimator",
            qasm2=dumps(circuit),
            options=self._options,
            session_id=self._session_id,
            amplitude_index=run_amplitude_index,
            observables=observables,
        )

        response = self._backend._api_client.submit_task(tasks)
        job_id = response.get("instanceId")
        if job_id is None:
            raise JobFailedError("Task submission failed (提交任务失败)")
        print(f"Task submitted successfully (提交任务成功), Task ID: {job_id}")
        return RuntimeJob(
            self._backend._api_client,
            job_id,
            observables if self._backend.name == "Guoji08" else (
                _result_observable if _result_observable is not None else observable
            ),
            backend_name=self._backend.name,
            shots=shots,
            circuit_type="estimator",
            num_qubits=(
                tasks["quantum-num"] if self._backend.name == "Guoji08"
                else circuit.num_qubits
            ),
        )
