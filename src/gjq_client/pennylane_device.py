"""PennyLane device backed by GJQ Runtime primitives."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from math import isfinite
from typing import Any

import numpy as np
import pennylane as qml
from pennylane import transform
from pennylane.measurements import ExpectationMP, VarianceMP, MidMeasureMP
from pennylane.tape import QuantumScript
from pennylane.transforms import split_non_commuting
from pennylane_qiskit import RemoteDevice
from pennylane_qiskit.converter import circuit_to_qiskit, mp_to_pauli
from qiskit.quantum_info import SparsePauliOp

from .backend.gjq_backend import GJQBackend
from .gjq_runtime.estimator import Estimator
from .gjq_runtime.sampler import Sampler
from .gjq_runtime.session import Session
from .gjq_runtime.submit_payload import sparsepauliop_to_observables
from .utils.exceptions import SessionClosedError

_MPS_BACKENDS = frozenset({"MPS"})


@transform
def _validate_measurements(tape, is_mps=False):
    """Reject unsupported execution requests before any cloud task is submitted."""
    if not tape.shots:
        raise ValueError("GJQDevice requires a finite number of shots")
    if tape.shots.has_partitioned_shots:
        raise ValueError("GJQDevice does not support a shot vector")
    if any(isinstance(op, MidMeasureMP) for op in tape.operations):
        raise ValueError("GJQDevice does not support mid-circuit measurements")
    for measurement in tape.measurements:
        if measurement.obs is None:
            continue
        paulis = measurement.obs.pauli_rep
        if paulis is None:
            raise ValueError("GJQDevice supports only Pauli observables")
        for coefficient in paulis.values():
            coefficient = complex(qml.math.unwrap(coefficient))
            if coefficient.imag != 0 or not isfinite(coefficient.real):
                raise ValueError("GJQ observable coefficients must be finite and real")
        if len(paulis) > 1 and not isinstance(measurement, (ExpectationMP, VarianceMP)):
            raise ValueError("Pauli sums support only expectation and variance measurements")
    return (tape,), lambda results: results[0]


@transform
def _expand_sum_variances(tape):
    """Use <A²> - <A>² for Pauli sums, including their covariance terms."""
    if not any(isinstance(mp, VarianceMP) and len(mp.obs.pauli_rep) > 1 for mp in tape.measurements):
        return (tape,), lambda results: results[0]
    measurements = []
    indices = []
    for measurement in tape.measurements:
        start = len(measurements)
        if isinstance(measurement, VarianceMP) and len(measurement.obs.pauli_rep) > 1:
            observable = measurement.obs
            measurements.extend([
                qml.expval(observable), qml.expval(qml.simplify(qml.prod(observable, observable)))
            ])
            indices.append((start, start + 1))
        else:
            measurements.append(measurement)
            indices.append((start,))

    def postprocess(results):
        values = results[0] if len(measurements) > 1 else (results[0],)
        output = tuple(
            values[index[1]] - values[index[0]] ** 2 if len(index) == 2 else values[index[0]]
            for index in indices
        )
        return output[0] if len(output) == 1 else output

    expanded = tape.copy(measurements=measurements)
    operation_parameters = len(tape.get_parameters(trainable_only=False, operations_only=True))
    expanded.trainable_params = (
        {index for index in tape.trainable_params if index < operation_parameters}
        | qml.math.get_trainable_indices(expanded.get_parameters(trainable_only=False))
    )
    return (expanded,), postprocess


def _expand_mps_parameter_shift(tape, *args, **kwargs):
    # Expand before gradient generation: PennyLane's variance shift rule treats
    # Pauli sums as involutory and otherwise drops d<A²>, including constant terms.
    (expanded,), variance_postprocess = _expand_sum_variances(tape)
    tapes, gradient_postprocess = qml.gradients.param_shift.expand_transform(
        expanded, *args, **kwargs
    )
    return tapes, lambda results: variance_postprocess((gradient_postprocess(results),))


@partial(
    transform,
    expand_transform=_expand_mps_parameter_shift,
    classical_cotransform=qml.gradients.param_shift.classical_cotransform,
    final_transform=True,
)
def _mps_parameter_shift(tape, *args, **kwargs):
    return qml.gradients.param_shift.tape_transform(tape, *args, **kwargs)


@transform
def _split_execution_types(tape, combine_estimator=False, split_sampler=False):
    """Send Pauli expectation values to Estimator and all other results to Sampler."""
    estimator = []
    sampler = []
    for index, measurement in enumerate(tape.measurements):
        target = (
            estimator
            if isinstance(measurement, ExpectationMP)
            and getattr(measurement.obs, "pauli_rep", None)
            else sampler
        )
        target.append((measurement, index))

    estimator_groups = []
    if estimator:
        estimator_groups.extend(
            [estimator] if combine_estimator else [[item] for item in estimator]
        )

    tapes = [
        QuantumScript(
            tape.operations,
            measurements=[measurement for measurement, _ in group],
            shots=tape.shots,
        )
        for group in estimator_groups
    ]
    sampler_postprocess = None
    if sampler:
        sampler_tape = QuantumScript(
            tape.operations,
            measurements=[measurement for measurement, _ in sampler],
            shots=tape.shots,
        )
        if split_sampler:
            sampler_tapes, sampler_postprocess = split_non_commuting(sampler_tape)
            tapes.extend(sampler_tapes)
        else:
            tapes.append(sampler_tape)

    def reorder(results):
        ordered = {}
        for group, group_result in zip(
            estimator_groups, results[: len(estimator_groups)], strict=True
        ):
            values = group_result if isinstance(group_result, tuple) else (group_result,)
            if len(group) != len(values):
                raise ValueError("GJQ measurement result count does not match the request")
            ordered.update(
                (index, value)
                for (_, index), value in zip(group, values, strict=True)
            )
        if sampler:
            sampler_results = results[len(estimator_groups) :]
            sampler_result = (
                sampler_postprocess(sampler_results)
                if sampler_postprocess is not None
                else sampler_results[0]
            )
            values = sampler_result if isinstance(sampler_result, tuple) else (sampler_result,)
            if len(sampler) != len(values):
                raise ValueError("GJQ measurement result count does not match the request")
            ordered.update(
                (index, value)
                for (_, index), value in zip(sampler, values, strict=True)
            )
        result = tuple(ordered[index] for index in range(len(tape.measurements)))
        return result[0] if len(result) == 1 else result

    return tapes, reorder


class GJQDevice(RemoteDevice):
    """PennyLane device that executes through GJQ Sampler and Estimator."""

    short_name = "gjq"

    def __init__(
        self,
        wires,
        backend: GJQBackend | None = None,
        mode: Session | None = None,
        shots=None,
        options: dict | None = None,
        timeout: float | None = None,
        **kwargs,
    ):
        if (backend is None) == (mode is None):
            raise ValueError("exactly one of backend or mode is required")
        if mode is not None:
            if not isinstance(mode, Session):
                raise ValueError("mode must be a GJQ Session")
            backend = mode.backend
        if not isinstance(backend, GJQBackend):
            raise ValueError("backend must be a GJQBackend")
        if backend.name in {"SAS-CPU", "SAS-GPU"}:
            raise ValueError(f"{backend.name} does not provide the measurement histogram required by GJQDevice")
        if options is not None and not isinstance(options, dict):
            raise ValueError("options must be a dict")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        if "session" in kwargs:
            raise ValueError("use mode for a GJQ Session")

        self._gjq_options = dict(options or {})
        self._timeout = timeout
        super().__init__(wires, backend=backend, shots=shots, session=mode, **kwargs)
        self._wire_map = {wire: index for index, wire in enumerate(self.wires)}
        unsupported = set(self._kwargs) - {"default_shots"}
        if unsupported:
            raise ValueError(
                f"unsupported device options: {sorted(unsupported)}; "
                "pass GJQ payload settings through options"
            )

    @property
    def _is_mps(self):
        return self.backend.name in _MPS_BACKENDS

    # Use the separate configuration hook to inspect original observables before
    # PennyLane's gradient expansion extracts trainable coefficients into postprocessing.
    preprocess = qml.devices.Device.preprocess

    def setup_execution_config(self, config=None, circuit=None):
        if self._is_mps and circuit is not None:
            _validate_measurements(circuit, is_mps=True)
        resolved = super().preprocess(config)[1]
        if self._is_mps and resolved.gradient_method is qml.gradients.param_shift:
            resolved = replace(resolved, gradient_method=_mps_parameter_shift)
        return resolved

    def preprocess_transforms(self, execution_config=None):
        pipeline, _ = super().preprocess(execution_config)
        pipeline.pop()  # PennyLane-Qiskit's primitive split; GJQ routes variance to Sampler.
        pipeline.pop()  # Expand sum variances before grouping or batching expectations.
        pipeline.add_transform(_expand_sum_variances)
        if not self._is_mps:
            pipeline.add_transform(split_non_commuting)
        pipeline.add_transform(
            _split_execution_types,
            combine_estimator=self._is_mps,
            split_sampler=self._is_mps,
        )
        validation = qml.CompilePipeline()
        validation.add_transform(_validate_measurements, is_mps=self._is_mps)
        return validation + pipeline

    def execute(self, circuits, execution_config=None):
        batch = (circuits,) if isinstance(circuits, QuantumScript) else tuple(circuits)
        if any(not circuit.shots for circuit in batch):
            raise ValueError("GJQDevice requires a finite number of shots")
        if any(circuit.shots.has_partitioned_shots for circuit in batch):
            raise ValueError("GJQDevice does not support a shot vector")
        if self.session is not None and getattr(self.session, "_closed", False):
            raise SessionClosedError("Cannot execute with a closed GJQ Session")
        return super().execute(batch, execution_config)

    def _mapped_circuit(self, circuit):
        return qml.map_wires(circuit, self._wire_map)[0][0]

    def _pauli_observable(self, measurement):
        return mp_to_pauli(measurement.map_wires(self._wire_map), self.num_wires)

    def _primitive_kwargs(self, session):
        return {"mode": session} if session is not None else {"backend": self.backend}

    def _execute_sampler(self, circuit, session):
        qcirc = circuit_to_qiskit(
            self._mapped_circuit(circuit), self.num_wires, diagonalize=True, measure=True
        )
        compiled = self.compile_circuits([qcirc])[0]
        sampler = Sampler(
            **self._primitive_kwargs(session), options=self._gjq_options
        )
        job = sampler.run(compiled, shots=circuit.shots.total_shots)
        self._current_job = job
        result = job.result(timeout=self._timeout)
        counts = result.get("counts")
        if self._is_mps:
            # MPS returns full physical-qubit strings, including transpiler ancillas.
            # The compiled measurements retain PennyLane's logical classical-bit order.
            measured = {
                compiled.find_bit(inst.clbits[0]).index: compiled.find_bit(inst.qubits[0]).index
                for inst in compiled.data if inst.operation.name == "measure"
            }
            if any(index not in measured for index in range(self.num_wires)):
                raise RuntimeError("GJQ MPS compiled circuit is missing logical measurements")
            if not isinstance(counts, dict) or not counts:
                raise RuntimeError("GJQ Sampler result is missing measurement counts")
            logical_counts = {}
            for state, frequency in counts.items():
                logical_state = "".join(state[-measured[index] - 1] for index in reversed(range(self.num_wires)))
                logical_counts[logical_state] = logical_counts.get(logical_state, 0) + frequency
            counts = logical_counts
        samples = self._samples_from_counts(
            counts, shots=circuit.shots.total_shots
        )
        self._samples = samples
        values = tuple(
            measurement.process_samples(samples, wire_order=self.wires)
            for measurement in circuit.measurements
        )
        return values

    def _execute_estimator(self, circuit, session):
        # The parent routes a leading VarianceMP here; preserve sampler semantics.
        # Hardware exposes sampling; derive its Pauli statistics in the measured basis.
        if (
            any(not isinstance(mp, ExpectationMP) for mp in circuit.measurements)
            or not getattr(self.backend.configuration(), "simulator", True)
        ):
            return self._execute_sampler(circuit, session)
        if self._is_mps:
            return self._execute_mps_estimator(circuit, session)

        values = []
        for measurement in circuit.measurements:
            result_observable = self._pauli_observable(measurement)
            if not self._supports_estimator_payload(result_observable):
                return self._execute_sampler(circuit, session)
            single = QuantumScript(
                circuit.operations, measurements=[measurement], shots=circuit.shots
            )
            qcirc = circuit_to_qiskit(
                self._mapped_circuit(single), self.num_wires, diagonalize=True, measure=True
            )
            compiled = self.compile_circuits([qcirc])[0]
            observable = self._apply_layout(result_observable, compiled)
            estimator = Estimator(
                **self._primitive_kwargs(session), options=self._gjq_options
            )
            job = estimator.run(
                compiled,
                shots=circuit.shots.total_shots,
                observable=observable,
                _result_observable=result_observable,
                _basis_rotated=True,
            )
            self._current_job = job
            result = job.result(timeout=self._timeout)
            value = result.get("evs")
            if (
                not isinstance(value, (int, float, np.number))
                or not np.isrealobj(value)
                or not np.isfinite(value)
            ):
                raise RuntimeError("GJQ Estimator result is missing a scalar evs value")
            values.append(float(value))
        return tuple(values)

    def _execute_mps_estimator(self, circuit, session):
        observables = [self._pauli_observable(mp) for mp in circuit.measurements]
        qcirc = circuit_to_qiskit(
            self._mapped_circuit(circuit), self.num_wires, diagonalize=False, measure=False
        )
        compiled = self.compile_circuits([qcirc])[0]
        observables = [
            self._apply_layout(observable, compiled)
            for observable in observables
        ]
        formulas, labels = self._mps_formulas(observables)
        if not labels:
            return tuple(float(constant) for constant, _ in formulas)

        compiled.measure_all()
        unit_observable = SparsePauliOp.from_list([(label, 1.0) for label in labels])
        estimator = Estimator(
            **self._primitive_kwargs(session), options=self._gjq_options
        )
        job = estimator.run(
            compiled,
            shots=circuit.shots.total_shots,
            observable=sparsepauliop_to_observables(unit_observable),
        )
        self._current_job = job
        result = job.result(timeout=self._timeout)
        evs = result.get("evs")
        if not isinstance(evs, dict):
            raise RuntimeError("GJQ MPS Estimator result is missing observable values")

        values = []
        for constant, terms in formulas:
            value = constant
            for name, coefficient in terms:
                if name not in evs:
                    raise RuntimeError(f"GJQ MPS result is missing observable {name}")
                observable_value = evs[name]
                if (
                    not isinstance(observable_value, (int, float, np.number))
                    or not np.isrealobj(observable_value)
                    or not np.isfinite(observable_value)
                ):
                    raise RuntimeError(f"GJQ MPS result has invalid observable {name}")
                value += coefficient * observable_value
            values.append(float(value))
        return tuple(values)

    @staticmethod
    def _apply_layout(observable, circuit):
        layout = getattr(circuit, "layout", None)
        return observable.apply_layout(layout) if layout is not None else observable

    @staticmethod
    def _supports_estimator_payload(observable):
        names = set()
        for label, coefficient in zip(
            observable.paulis.to_labels(), observable.coeffs, strict=True
        ):
            coefficient = complex(coefficient)
            sites = [
                (pauli, len(label) - index - 1)
                for index, pauli in enumerate(label)
                if pauli != "I"
            ]
            if (
                len(sites) != 1
                or coefficient.imag != 0
                or not isfinite(coefficient.real)
            ):
                return False
            pauli, qubit = sites[0]
            name = f"{pauli}{qubit}"
            if name in names:
                return False
            names.add(name)
        return bool(names)

    @staticmethod
    def _mps_formulas(observables):
        formulas = []
        labels = {}
        for observable in observables:
            constant = 0.0
            terms = []
            for label, coefficient in zip(
                observable.paulis.to_labels(), observable.coeffs, strict=True
            ):
                coefficient = complex(coefficient)
                if coefficient.imag != 0 or not isfinite(coefficient.real):
                    raise ValueError("MPS observable coefficients must be finite and real")
                sites = [
                    (pauli, len(label) - index - 1)
                    for index, pauli in enumerate(label)
                    if pauli != "I"
                ]
                if not sites:
                    constant += coefficient.real
                    continue
                name = "".join(f"{pauli}{qubit}" for pauli, qubit in reversed(sites))
                labels.setdefault(label, name)
                terms.append((name, coefficient.real))
            formulas.append((constant, terms))
        return formulas, tuple(labels)

    def _samples_from_counts(self, counts: Any, shots: int | None = None):
        if not isinstance(counts, dict) or not counts:
            raise RuntimeError("GJQ Sampler result is missing measurement counts")
        # MPS returns normalized probabilities, including deterministic 1.0 results.
        probabilities = self._is_mps and any(type(value) is float for value in counts.values())
        samples = []
        for state, count in counts.items():
            state = str(state).replace(" ", "")
            if (
                set(state) - {"0", "1"}
                or len(state) != self.num_wires
                or type(count) not in ((int, float) if probabilities else (int,))
                or not isfinite(count)
                or count < 0
                or (probabilities and count > 1)
            ):
                raise RuntimeError("GJQ Sampler returned invalid measurement counts")
            bits = [int(bit) for bit in state[::-1]]
            if probabilities:
                samples.append(bits)
            else:
                samples.extend([bits] * count)
        if probabilities:
            weights = np.asarray(list(counts.values()), dtype=float)
            total = weights.sum()
            if not np.isclose(total, 1.0, rtol=0, atol=1e-6):
                raise RuntimeError("GJQ MPS probabilities must sum to one")
            if type(shots) is not int or shots <= 0:
                raise RuntimeError("GJQ MPS probabilities require positive integer shots")
            # Recover normalized shot counts without adding a second sampling error.
            expected = weights / total * shots
            frequencies = np.floor(expected).astype(int)
            remainder = shots - int(frequencies.sum())
            order = np.argsort(-(expected - frequencies), kind="stable")
            frequencies[order[:remainder]] += 1
            return np.repeat(np.asarray(samples, dtype=int), frequencies, axis=0)
        if not samples:
            raise RuntimeError("GJQ Sampler returned zero samples")
        return np.asarray(samples, dtype=int)


__all__ = ["GJQDevice"]
