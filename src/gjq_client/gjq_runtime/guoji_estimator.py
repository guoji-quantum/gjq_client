"""Guoji08's native Estimator wire encoding and named-result reconstruction."""

from math import isfinite

from qiskit import ClassicalRegister, QuantumCircuit

from ..utils.exceptions import GJQValidationError, RuntimeJobFailureError


def _pauli_label(term: dict, num_qubits: int) -> str:
    # The cloud uses ascending physical-qubit order, unlike Qiskit's labels.
    label = ["I"] * num_qubits
    for pauli, qubit in zip(term["pauli"], term["qubits"], strict=True):
        label[qubit] = pauli
    return "".join(label)


def encode_guoji_observables(observables: list[dict], num_qubits: int) -> list[dict]:
    """Pad every Pauli to the same width so Z0 and Z1 cannot share a cloud key."""
    return [
        {
            "name": observable["name"],
            "terms": [
                {
                    "coeff": term["coeff"],
                    "pauli": _pauli_label(term, num_qubits),
                    "qubits": list(range(num_qubits)),
                }
                for term in observable["terms"]
            ],
        }
        for observable in observables
    ]


def prepare_guoji_measurements(
    circuit: QuantumCircuit, observables: list[dict]
) -> QuantumCircuit:
    """Normalize the terminal measurement span without changing the caller's circuit."""
    measured = set()
    occupied = set()
    for instruction in circuit.data:
        qubits = {circuit.find_bit(qubit).index for qubit in instruction.qubits}
        if instruction.operation.name != "barrier":
            occupied.update(qubits)
        if instruction.operation.name == "measure":
            measured.update(qubits)
        elif instruction.operation.name != "barrier" and measured.intersection(qubits):
            raise GJQValidationError(
                "Guoji08 Estimator does not support gates after measurement on the same qubit"
            )
    observable_qubits = {
        qubit
        for observable in observables
        for term in observable["terms"]
        for qubit in term["qubits"]
    }
    layout = getattr(circuit, "layout", None)
    final_index_layout = getattr(layout, "final_index_layout", None)
    mapping = final_index_layout() if callable(final_index_layout) else None
    logical_width = len(mapping) if mapping else circuit.num_qubits
    width = max(logical_width, max(occupied | observable_qubits, default=0) + 1)
    # Guoji08's Pauli positions require a complete measurement span, including I sites.
    # Unused transpiler ancillas outside that span do not belong to the request.
    result = circuit.remove_final_measurements(inplace=False)
    names = {register.name for register in result.qregs + result.cregs}
    name = "estimator"
    while name in names:
        name += "_"
    register = ClassicalRegister(width, name)
    result.add_register(register)
    for qubit in range(width):
        result.measure(qubit, register[qubit])
    return result


def validate_guoji_measurements(payload: dict) -> None:
    """Require complete terminal measurements for direct JSON submissions."""
    measured = set()
    for step in payload.get("steps", []):
        for gate in step.get("gates", []):
            name = gate.get("name")
            if name == "measure":
                measured.update(gate.get("targets", []))
            elif name not in {"barrier", "delay"}:
                qubits = set(gate.get("targets", [])) | {
                    control["target"] for control in gate.get("controls", [])
                }
                if measured.intersection(qubits):
                    raise GJQValidationError(
                        "Guoji08 Estimator does not support gates after measurement on the same qubit"
                    )
    missing = set(range(payload["quantum-num"])) - measured
    if missing:
        raise GJQValidationError(
            f"Guoji08 Estimator requires a complete measurement span; missing {sorted(missing)}. "
            "Use Estimator.run to prepare terminal measurements automatically."
        )


def decode_guoji_expectations(
    raw_evs: object, observables: list[dict], num_qubits: int
) -> dict[str, float]:
    """Rebuild independent named sums from unweighted full-width Pauli values."""
    if isinstance(raw_evs, dict) and "observables" in raw_evs:
        raw_evs = raw_evs["observables"]
    if not isinstance(raw_evs, dict):
        raise RuntimeJobFailureError("Guoji08 result missing per-Pauli observable values")
    if any(type(value) not in (int, float) or not isfinite(value)
           for value in raw_evs.values()):
        raise RuntimeJobFailureError("Invalid Guoji08 observable values")
    result = {}
    for observable in observables:
        coefficients = {}
        for term in observable["terms"]:
            label = _pauli_label(term, num_qubits)
            coefficients[label] = coefficients.get(label, 0.0) + term["coeff"]
        value = 0.0
        for label, coefficient in coefficients.items():
            if coefficient == 0:
                continue
            if set(label) == {"I"}:
                value += coefficient
            elif label in raw_evs:
                value += coefficient * raw_evs[label]
            else:
                raise RuntimeJobFailureError(
                    f"Guoji08 result missing observable values: {observable['name']} ({label})"
                )
        if not isfinite(value):
            raise RuntimeJobFailureError("Invalid Guoji08 observable sum")
        result[observable["name"]] = value
    return result
