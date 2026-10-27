"""Shared submit payload builders for Sampler / Estimator."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any
import warnings

from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp

from ..utils.exceptions import GJQValidationError as ValueError


_SIMPLE_PRESETS = frozenset({"fast", "balanced", "accurate"})
_MPS_BACKEND_NAMES = frozenset({"MPS"})
_AMPLITUDE_INDEX_BACKEND_NAMES = frozenset({"SAS-CPU", "SAS-GPU"})
_ALLOWED_DTYPES = frozenset({"complex64", "complex128"})
_SVD_SIMPLE = frozenset({"gesvd", "gesvdp"})
_MAX_NUM_GPUS = 2
_MPS_GATE_WARNING = 50_000
_MPS_GATE_REJECTION = 100_000
_MPS_MAX_OBSERVABLES = 3_000
_MPS_WIDE_QUBITS = 100
_MPS_RECOMMENDED_DEPTH = 20
_MPS_KEYS = frozenset(
    {"max_bond_dimension", "abs_cutoff", "rel_cutoff", "discarded_weight_cutoff"}
)


def validate_shots(shots: Any, *, backend_name: str | None = None) -> int:
    if backend_name in _MPS_BACKEND_NAMES:
        _integer_in_range(shots, 0, 1_000_000, "shots")
    elif type(shots) is not int or shots <= 0:
        raise ValueError("shots must be a positive integer")
    return shots


def _require_keys(obj: dict, keys: set[str], where: str) -> None:
    got = set(obj)
    if got != keys:
        raise ValueError(f"{where} keys must be {sorted(keys)}, got {sorted(got)}")


def _integer_in_range(value: Any, minimum: int, maximum: int, where: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{where} must be an integer in [{minimum}, {maximum}]")


def _number_in_range(
    value: Any, minimum: float, maximum: float, where: str, *, allow_zero: bool = False
) -> None:
    if (
        type(value) not in (int, float)
        or not (minimum <= value <= maximum or (allow_zero and value == 0))
        or not isfinite(value)
    ):
        zero = " or 0" if allow_zero else ""
        raise ValueError(f"{where} must be a finite number in [{minimum}, {maximum}]{zero}")


def _validate_runtime(runtime: Any) -> None:
    if not isinstance(runtime, dict):
        raise ValueError("simulator_config.runtime must be a dict")
    _require_keys(runtime, {"num_gpus"}, "simulator_config.runtime")
    _integer_in_range(runtime["num_gpus"], 1, _MAX_NUM_GPUS, "simulator_config.runtime.num_gpus")


def validate_simulator_config(config: Any) -> None:
    """Validate MPS simulator_config nested in Estimator/Sampler options."""
    if not isinstance(config, dict):
        raise ValueError("simulator_config must be a dict")
    preset = config.get("preset")
    if isinstance(preset, str) and preset in _SIMPLE_PRESETS:
        _require_keys(config, {"preset", "runtime"}, "simulator_config")
        _validate_runtime(config["runtime"])
        return
    if preset != "expert":
        raise ValueError(
            "simulator_config.preset must be one of: fast, balanced, accurate, expert"
        )
    _require_keys(
        config, {"preset", "dtype", "mps", "svd", "runtime"}, "simulator_config"
    )
    if not isinstance(config["dtype"], str) or config["dtype"] not in _ALLOWED_DTYPES:
        raise ValueError(
            "simulator_config.dtype must be one of: complex64, complex128"
        )
    _validate_runtime(config["runtime"])
    mps = config["mps"]
    if not isinstance(mps, dict):
        raise ValueError("simulator_config.mps must be a dict")
    _require_keys(mps, _MPS_KEYS, "simulator_config.mps")
    _integer_in_range(mps["max_bond_dimension"], 2, 4096, "simulator_config.mps.max_bond_dimension")
    for key in ("abs_cutoff", "rel_cutoff", "discarded_weight_cutoff"):
        maximum = 1e-4 if key == "discarded_weight_cutoff" else 1e-2
        _number_in_range(mps[key], 1e-18, maximum, f"simulator_config.mps.{key}")
    svd = config["svd"]
    if not isinstance(svd, dict):
        raise ValueError("simulator_config.svd must be a dict")
    algorithm = svd.get("algorithm")
    if isinstance(algorithm, str) and algorithm in _SVD_SIMPLE:
        _require_keys(svd, {"algorithm"}, "simulator_config.svd")
        return
    if algorithm != "gesvdj":
        raise ValueError(
            "simulator_config.svd.algorithm must be one of: gesvd, gesvdp, gesvdj"
        )
    _require_keys(
        svd, {"algorithm", "gesvdj_tol", "gesvdj_max_sweeps"}, "simulator_config.svd"
    )
    _number_in_range(svd["gesvdj_tol"], 1e-18, 1e-2, "simulator_config.svd.gesvdj_tol", allow_zero=True)
    _integer_in_range(svd["gesvdj_max_sweeps"], 1, 200, "simulator_config.svd.gesvdj_max_sweeps")


def ensure_circuit_has_measure(circuit: QuantumCircuit) -> None:
    if not any(
        getattr(instruction.operation, "name", None) == "measure"
        for instruction in circuit.data
    ):
        raise ValueError("circuit must contain at least one measure operation")


def ensure_run_fits_backend(
    circuit: QuantumCircuit, shots: Any, backend: Any
) -> None:
    validate_shots(shots, backend_name=backend.name)
    if backend.name in _MPS_BACKEND_NAMES and circuit.num_qubits < 2:
        raise ValueError("MPS requires at least 2 qubits (MPS 至少需要 2 个比特)")
    configuration = backend.configuration()
    max_qubits = getattr(configuration, "n_qubits", None)
    if type(max_qubits) is int:
        if max_qubits <= 0:
            raise ValueError("backend n_qubits must be a positive integer")
        if circuit.num_qubits > max_qubits:
            raise ValueError(
                f"circuit uses {circuit.num_qubits} qubits, but backend "
                f"'{backend.name}' supports at most {max_qubits}"
            )

    max_shots = getattr(configuration, "max_shots", None)
    if type(max_shots) is int:
        if max_shots <= 0:
            raise ValueError("backend max_shots must be a positive integer")
        if shots > max_shots:
            raise ValueError(
                f"shots {shots} exceeds backend '{backend.name}' limit {max_shots}"
            )


def validate_amplitude_index(value: Any, n_qubits: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError("amplitude-index must be a non-empty list")
    if len(value) != 1:
        raise ValueError("amplitude-index must contain exactly one index")
    if type(n_qubits) is not int or n_qubits <= 0:
        raise ValueError("quantum-num must be a positive integer")
    if any(type(index) is not int for index in value):
        raise ValueError("amplitude-index values must be integers")
    if any(index < 0 or index.bit_length() > n_qubits for index in value):
        raise ValueError("amplitude-index values must satisfy 0 <= index < 2**quantum-num")
    return value


def sparsepauliop_to_observables(obs: Any) -> list[dict]:
    """Convert Pauli terms to named observables in ascending qubit order."""
    observables = []
    names = set()
    for label, c in zip(obs.paulis.to_labels(), obs.coeffs):
        sites = [
            (pauli, index)
            for index, pauli in enumerate(reversed(label))
            if pauli != "I"
        ]
        if not sites:
            raise ValueError("each observable term must act on at least one qubit")
        if c.imag != 0:
            raise ValueError("observable coeff must be real")
        coeff = float(c.real)
        if not isfinite(coeff):
            raise ValueError("observable coeff must be finite")
        pauli = "".join(p for p, _ in sites)
        qubits = [q for _, q in sites]
        name = "".join(f"{p}{q}" for p, q in sites)
        if name in names:
            raise ValueError("observable names must be unique")
        names.add(name)
        observables.append(
            {
                "name": name,
                "terms": [{"coeff": coeff, "pauli": pauli, "qubits": qubits}],
            }
        )
    return observables


def sparsepauliop_to_mps_observables(obs: SparsePauliOp) -> list[dict]:
    """Convert one ``SparsePauliOp`` into one MPS named observable.

    A multi-term ``SparsePauliOp`` represents one Hamiltonian, so its terms stay
    grouped under the stable ``observable`` name.  Single non-identity terms
    retain the historical Pauli/qubit-derived name.  The MPS request schema has
    no zero-qubit representation, so an identity term uses qubit 0 as a neutral
    placeholder.
    """
    terms = []
    single_name = ""
    for label, coefficient in zip(
        obs.paulis.to_labels(), obs.coeffs, strict=True
    ):
        coefficient = complex(coefficient)
        if coefficient.imag != 0:
            raise ValueError("observable coeff must be real")
        coeff = float(coefficient.real)
        if not isfinite(coeff):
            raise ValueError("observable coeff must be finite")
        sites = [
            (pauli, index)
            for index, pauli in enumerate(reversed(label))
            if pauli != "I"
        ]
        if sites:
            pauli = "".join(item[0] for item in sites)
            qubits = [item[1] for item in sites]
            single_name = "".join(
                f"{item_pauli}{qubit}" for item_pauli, qubit in sites
            )
        else:
            pauli = "I"
            qubits = [0]
            single_name = "I0"
        terms.append({"coeff": coeff, "pauli": pauli, "qubits": qubits})
    if not terms:
        raise ValueError("observable must contain at least one Pauli term")
    return [{"name": single_name if len(terms) == 1 else "observable", "terms": terms}]


def validate_observables(observables: list[dict], num_qubits: int) -> None:
    """Validate named sums supplied in the request-body format."""
    if not isinstance(observables, list) or not observables:
        raise ValueError("observables must be a non-empty list")
    names = set()
    for observable in observables:
        if not isinstance(observable, dict):
            raise ValueError("observable must be a dict")
        _require_keys(observable, {"name", "terms"}, "observable")
        name, terms = observable["name"], observable["terms"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("observable names must be non-empty and unique")
        names.add(name)
        if not isinstance(terms, list) or not terms:
            raise ValueError("observable terms must be a non-empty list")
        for term in terms:
            if not isinstance(term, dict):
                raise ValueError("observable term must be a dict")
            _require_keys(term, {"coeff", "pauli", "qubits"}, "observable term")
            coeff, pauli, qubits = term["coeff"], term["pauli"], term["qubits"]
            if type(coeff) not in (int, float) or not isfinite(coeff):
                raise ValueError("observable coeff must be finite and real")
            if not isinstance(pauli, str) or not pauli or set(pauli) - set("IXYZ"):
                raise ValueError("observable pauli must contain only I, X, Y, Z")
            if (
                not isinstance(qubits, list) or len(qubits) != len(pauli)
                or any(type(q) is not int or not 0 <= q < num_qubits for q in qubits)
                or len(set(qubits)) != len(qubits)
            ):
                raise ValueError("observable qubits must be unique, in range, and match pauli")


def validate_z_basis_observables(observables: list[dict]) -> None:
    """Reject observables that cannot be derived from Z-basis measurement counts."""
    unsupported = sorted({
        pauli
        for observable in observables
        for term in observable["terms"]
        for pauli in term["pauli"]
        if pauli not in {"I", "Z"}
    })
    if unsupported:
        raise ValueError(
            "non-MPS Estimator supports only I/Z observables because the cloud result "
            "contains Z-basis counts; X/Y observables require an explicit basis rotation "
            f"before measurement (unsupported: {unsupported})"
        )


def validate_mps_payload(payload: dict) -> None:
    """Apply the MPS limits to direct RuntimeClient submissions as well."""
    validate_simulator_config(payload.get("simulator_config"))
    validate_shots(payload.get("repetitions"), backend_name="MPS")
    if payload.get("circuit-type") == "sampler" and payload["repetitions"] == 0:
        raise ValueError("MPS Sampler requires positive integer shots")
    num_qubits = payload.get("quantum-num")
    if type(num_qubits) is not int or num_qubits < 2:
        raise ValueError("MPS quantum-num must be an integer >= 2 (MPS 至少需要 2 个比特)")
    observables = payload.get("observables")
    if isinstance(observables, list) and len(observables) > _MPS_MAX_OBSERVABLES:
        raise ValueError(
            f"MPS supports at most {_MPS_MAX_OBSERVABLES} observables per task; got {len(observables)} "
            "(MPS 每个任务的观测量总数不得超过 3000)"
        )
    if observables is not None or payload.get("circuit-type") == "estimator":
        validate_observables(observables, num_qubits)
    _validate_mps_workload(payload, num_qubits)


def _validate_mps_workload(payload: dict, num_qubits: int) -> None:
    """Count the serialized workload, after compilation and measurement removal.

    Each emitted gate counts once, including controlled gates. Depth counts occupied
    computation steps, not step indices or the original algorithm/template layers.
    RuntimeClient calls this once at the shared submission boundary for all APIs.
    """
    gate_count = 0
    depth = 0
    steps = payload.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("MPS steps must be a list")
    measured = set()
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("gates"), list):
            raise ValueError("MPS step must contain a gates list")
        count = 0
        for gate in step["gates"]:
            if not isinstance(gate, dict) or not isinstance(gate.get("name"), str) or not gate["name"]:
                raise ValueError("MPS gate must contain a name")
            targets, controls = gate.get("targets"), gate.get("controls", [])
            if not isinstance(targets, list) or not targets or not isinstance(controls, list):
                raise ValueError("MPS gate must contain targets and a valid controls list")
            if any(not isinstance(control, dict) or "target" not in control for control in controls):
                raise ValueError("MPS gate control must contain a target")
            qubits = targets + [control["target"] for control in controls]
            if any(type(qubit) is not int or not 0 <= qubit < num_qubits for qubit in qubits):
                raise ValueError("MPS gate qubits must be integers in range")
            if gate["name"] == "measure":
                measured.update(targets)
            elif gate["name"] not in {"barrier", "delay"}:
                if measured.intersection(qubits):
                    raise ValueError("MPS does not support gates after measurement on the same qubit")
                count += 1
        gate_count += count
        depth += bool(count)
    if gate_count >= _MPS_GATE_REJECTION:
        raise ValueError(
            f"MPS final circuit has {gate_count} gates; gate count must be < {_MPS_GATE_REJECTION} "
            "(MPS 最终提交线路总门数达到 10 万，拒绝提交，请减少门数)"
        )
    advice = []
    if gate_count >= _MPS_GATE_WARNING:
        advice.append(
            f"MPS final circuit has {gate_count} gates (warning threshold: {_MPS_GATE_WARNING}). "
            "MPS 最终提交线路总门数已达到 5 万，运行时间和资源消耗可能较高。"
        )
    if num_qubits >= _MPS_WIDE_QUBITS and depth > _MPS_RECOMMENDED_DEPTH:
        advice.append(
            f"MPS final circuit uses {num_qubits} qubits and {depth} computational layers. "
            "比特数较大时（数百～1000），近邻线路建议控制在约 20 层以内；"
            "超过后截断误差和运行时间可能明显增加。该建议不代表其他线路在 20 层以内就一定可控。"
        )
    if advice:
        warnings.warn(" ".join(advice), UserWarning, stacklevel=3)


def ensure_observables_are_measured(
    circuit: QuantumCircuit, observables: list[dict]
) -> None:
    measured_qubits = {
        circuit.find_bit(instruction.qubits[0]).index
        for instruction in circuit.data
        if getattr(instruction.operation, "name", None) == "measure"
    }
    observable_qubits = {
        qubit
        for observable in observables
        for term in observable["terms"]
        for qubit in term["qubits"]
    }
    missing = sorted(observable_qubits - measured_qubits)
    if missing:
        raise ValueError(f"observable qubits are not measured: {missing}")


def build_submit_payload(
    *,
    backend_name: str,
    shots: int,
    instructions: dict,
    circuit_type: str,
    qasm2: str,
    options: dict | None = None,
    session_id: str | None = None,
    amplitude_index: list[int] | None = None,
    observables: list[dict] | None = None,
) -> dict:
    """Build submitTask payload; core fields always win over options."""
    validate_shots(shots, backend_name=backend_name)
    if not instructions.get("steps") and not instructions.get("quantum-num"):
        raise ValueError("circuit is empty")

    if options is not None and not isinstance(options, dict):
        raise ValueError("options must be a dict")
    tasks = dict(options or {})
    if backend_name in _MPS_BACKEND_NAMES and "simulator_config" not in tasks:
        raise ValueError(
            f"backend '{backend_name}' requires options['simulator_config']"
        )
    if "simulator_config" in tasks:
        validate_simulator_config(tasks["simulator_config"])
    tasks.update(instructions)
    tasks["repetitions"] = shots
    tasks["device_name"] = backend_name
    tasks["circuit-type"] = circuit_type
    tasks["qasm2"] = qasm2
    tasks.pop("qubit_num", None)
    tasks.pop("measure-position", None)
    if backend_name in _MPS_BACKEND_NAMES:
        tasks["measure-position"] = sorted({
            q for step in instructions["steps"] for gate in step["gates"]
            if gate["name"] == "measure" for q in gate["targets"]
        })
        tasks["steps"] = deepcopy(instructions["steps"])
        measured = set()
        for step in tasks["steps"]:
            for gate in step["gates"]:
                if gate["name"] == "measure":
                    measured.update(gate["targets"])
                elif measured.intersection(gate["targets"] + [c["target"] for c in gate.get("controls", [])]):
                    raise ValueError("MPS does not support gates after measurement on the same qubit")
            step["gates"] = [gate for gate in step["gates"] if gate["name"] != "measure"]
            for gate in step["gates"]:
                for control in gate.get("controls", []):
                    control.setdefault("state", "1")
        tasks["steps"] = [step for step in tasks["steps"] if step["gates"]]

    if backend_name in _AMPLITUDE_INDEX_BACKEND_NAMES:
        validate_amplitude_index(amplitude_index, instructions.get("quantum-num"))
        tasks["amplitude-index"] = amplitude_index
    elif amplitude_index is not None:
        raise ValueError("amplitude_index is only supported by SAS-CPU and SAS-GPU")
    tasks.pop("sparsepauliop", None)
    if backend_name == "Guoji08" and circuit_type == "estimator":
        from .guoji_estimator import encode_guoji_observables

        observables = encode_guoji_observables(observables, tasks["quantum-num"])
    tasks["observables"] = observables
    if session_id is not None:
        tasks["session_id"] = session_id
    else:
        tasks.pop("session_id", None)
    return tasks
