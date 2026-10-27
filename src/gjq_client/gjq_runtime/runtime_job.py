"""RuntimeJob类, 实现下面的功能：
- 获取job状态
- 获取job结果
- 获取job日志
- 等待job完成
"""

from math import floor, isclose, isfinite
from typing import Any, Literal
import time

from ..client.runtime import RuntimeClient
from ..utils.exceptions import (
    RuntimeJobFailureError,
    RuntimeJobTimeoutError,
)

JobStatus = Literal["INITIALIZING", "QUEUED", "RUNNING", "CANCELLED", "DONE", "ERROR"]
_RESULT_POLL_INTERVAL = 0.5
_RESULT_POLL_ATTEMPTS = 5


class _ResultNotReady(Exception):
    """Internal signal for a completed job whose result is not visible yet."""


def _result_payload_is_pending(result: dict) -> bool:
    """Return whether the response contains only metadata or empty placeholders."""
    # Explicit result fields, even when empty, are complete but invalid payloads.
    # Only absent data or empty transport wrappers indicate propagation delay.
    if any(
        key in result
        for key in ("counts", "freq_res", "optimize_circuit", "evs")
    ):
        return False
    wrapper_keys = ("result", "data", "estimator_result")
    present = [result[key] for key in wrapper_keys if key in result]
    if not present:
        return True
    return all(value is None or value == {} or value == [] for value in present)


API_TO_JOB_STATUS: dict[str, JobStatus] = {
    "INITIALIZING": "INITIALIZING",
    "pending": "QUEUED",
    "running": "RUNNING",
    "completed": "DONE",
    "failed": "ERROR",
    "error": "ERROR",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "CANCELLED": "CANCELLED",
}


def _get_expectation_value(counts, pauli_op):
    if not isinstance(counts, dict) or not counts:
        raise RuntimeJobFailureError(
            "Cannot compute expectation value without measurement counts "
            "(缺少测量结果，无法计算期望值)"
        )

    expectation = 0
    if any(type(value) not in (int, float) or not isfinite(value) or value < 0
           for value in counts.values()):
        raise RuntimeJobFailureError("Invalid measurement counts for expectation value")
    total_shots = sum(counts.values())
    if not isfinite(total_shots) or total_shots <= 0:
        raise RuntimeJobFailureError("Cannot compute expectation value from zero or invalid total counts")

    for pauli, coeff in zip(pauli_op.paulis, pauli_op.coeffs):
        pauli_label = pauli.to_label()[::-1]
        unsupported = sorted(set(pauli_label) - {"I", "Z"})
        if unsupported:
            raise RuntimeJobFailureError(
                "Cannot compute X/Y expectation values from Z-basis measurement counts; "
                f"apply an explicit basis rotation before measurement (unsupported: {unsupported})"
            )
        exp_val = 0

        for b, c in counts.items():
            bitstring = b[::-1]
            if len(bitstring) < len(pauli_label):
                raise RuntimeJobFailureError(
                    f"Measurement bitstring width {len(bitstring)} is smaller than "
                    f"observable width {len(pauli_label)} "
                    f"(测量比特串宽度小于观测量宽度)"
                )
            parity = sum(
                int(bitstring[i])
                for i, p in enumerate(pauli_label) if p != "I"
            ) % 2

            exp_val += ((-1) ** parity) * c
        exp_val /= total_shots
        expectation += coeff * exp_val
    return expectation.real


def _counts_from_result(result: dict) -> dict | None:
    # Hardware can include a normalized probability summary beside shot counts.
    # Keep the original bitstring counts authoritative when both are present.
    counts = {
        state: value for state, value in result.items()
        if isinstance(state, str) and state and not set(state.replace(" ", "")) - {"0", "1"}
        and state.replace(" ", "")
    }
    if counts:
        return counts

    counts = result.get("counts", result.get("result"))
    if isinstance(counts, dict) and counts:
        return counts

    freq_res = result.get("freq_res")
    if freq_res is None:
        return None
    if not isinstance(freq_res, list):
        raise RuntimeJobFailureError("Invalid MPS freq_res result")

    counts = {}
    for item in freq_res:
        if not isinstance(item, dict):
            raise RuntimeJobFailureError("Invalid MPS freq_res item")
        state, frequency = item.get("qState"), item.get("freq")
        if not isinstance(state, str) or not state or set(state) - {"0", "1"}:
            raise RuntimeJobFailureError("Invalid qState in MPS freq_res")
        if type(frequency) is not int or frequency < 0:
            raise RuntimeJobFailureError("Invalid freq in MPS freq_res")
        if state in counts:
            raise RuntimeJobFailureError("Duplicate qState in MPS freq_res")
        counts[state] = frequency
    return counts or None


def _normalize_mps_counts(
    counts: dict,
    shots: int | None,
    num_qubits: int | None = None,
) -> tuple[dict | None, dict | None]:
    """Separate MPS probabilities and recover an exact shot histogram."""
    if any(
        not isinstance(state, str) or not state or set(state) - {"0", "1"}
        for state in counts
    ):
        raise RuntimeJobFailureError("Invalid binary state in MPS counts")
    widths = {len(state) for state in counts}
    if len(widths) != 1 or (num_qubits is not None and widths != {num_qubits}):
        raise RuntimeJobFailureError("MPS measurement bitstring width mismatch")
    if not any(type(value) is float for value in counts.values()):
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise RuntimeJobFailureError("Invalid MPS integer counts")
        total = sum(counts.values())
        if total <= 0 or (type(shots) is int and shots > 0 and total != shots):
            raise RuntimeJobFailureError("MPS integer counts total must match positive shots")
        return counts, None
    if any(
        type(value) not in (int, float)
        or not isfinite(value)
        or value < 0
        or value > 1
        for value in counts.values()
    ):
        raise RuntimeJobFailureError("Invalid MPS probabilities")
    total = sum(counts.values())
    if not isclose(total, 1.0, rel_tol=0, abs_tol=1e-6):
        raise RuntimeJobFailureError("MPS probabilities must sum to one")
    probabilities = {state: value / total for state, value in counts.items()}
    if type(shots) is not int or shots <= 0:
        return None, probabilities

    expected = [probability * shots for probability in probabilities.values()]
    frequencies = [floor(value) for value in expected]
    remainder = shots - sum(frequencies)
    order = sorted(
        range(len(expected)),
        key=lambda index: (-(expected[index] - frequencies[index]), index),
    )
    for index in order[:remainder]:
        frequencies[index] += 1
    normalized_counts = {
        state: frequency
        for state, frequency in zip(probabilities, frequencies)
        if frequency
    }
    return normalized_counts, probabilities


def _validate_evs(evs: Any) -> bool:
    """Empty values are absent; present values must be finite real numbers."""
    if isinstance(evs, dict):
        if any(not isinstance(name, str) or not name for name in evs):
            raise RuntimeJobFailureError("Invalid observable name in evs")
        values = list(evs.values())
    elif isinstance(evs, list):
        values = evs
    else:
        values = [evs]
    if any(type(value) not in (int, float) or not isfinite(value) for value in values):
        raise RuntimeJobFailureError("Invalid observable values in evs: expected finite real numbers")
    return bool(values)


def _evs_from_result(result: dict) -> tuple[bool, Any]:
    if "evs" in result and result["evs"] is not None:
        evs = result["evs"]
        if isinstance(evs, dict) and "values" in evs and "observables" in evs:
            evs = evs["observables"] or evs["values"]
        return _validate_evs(evs), evs

    optimize_circuit = result.get("optimize_circuit")
    if not isinstance(optimize_circuit, dict):
        return False, None
    observables = optimize_circuit.get("observables")
    if observables is None:
        return False, None
    if not isinstance(observables, list) or not observables:
        raise RuntimeJobFailureError("Invalid MPS observables result")

    evs = {}
    for item in observables:
        if not isinstance(item, dict):
            raise RuntimeJobFailureError("Invalid MPS observable result")
        name, value = item.get("name"), item.get("value")
        if not isinstance(name, str) or not name or name in evs:
            raise RuntimeJobFailureError("Invalid or duplicate MPS observable name")
        if type(value) not in (int, float) or not isfinite(value):
            raise RuntimeJobFailureError("Invalid MPS observable value")
        evs[name] = value
    return True, evs


def _guoji_result_width(raw_evs: object, observables: list[dict]) -> int:
    """Recover a missing task width only from the cloud's full-width Pauli keys."""
    if isinstance(raw_evs, dict) and "observables" in raw_evs:
        raw_evs = raw_evs["observables"]
    if not isinstance(raw_evs, dict) or any(
        not isinstance(label, str) or not label or set(label) - set("IXYZ")
        for label in raw_evs
    ):
        raise RuntimeJobFailureError("Invalid Guoji08 full-width Pauli labels")
    widths = {len(label) for label in raw_evs}
    requested_width = max(
        qubit for observable in observables
        for term in observable["terms"] for qubit in term["qubits"]
    ) + 1
    if len(widths) > 1 or (widths and next(iter(widths)) < requested_width):
        raise RuntimeJobFailureError("Guoji08 Pauli width does not match the requested observables")
    # Empty tables are usable only for identity/zero/cancelled terms.  The decoder
    # still rejects every nonzero nonidentity term whose Pauli value is absent.
    return next(iter(widths)) if widths else requested_width


def _map_task_state(
    task_state: str | None,
    previous: JobStatus | None = None,
) -> JobStatus:
    """Map cloud task_state to JobStatus.

    Known failures/cancels become final. Unknown strings stay non-final so a
    future transitional state does not fail closed; timeout still bounds waits.
    """
    if task_state is None:
        return previous if previous and previous not in RuntimeJob.JOB_FINAL_STATES else "RUNNING"
    mapped = API_TO_JOB_STATUS.get(task_state)
    if mapped is not None:
        return mapped
    if previous and previous not in RuntimeJob.JOB_FINAL_STATES:
        return previous
    return "RUNNING"


class RuntimeJob():
    """RuntimeJob类, 实现下面的功能：
    - 获取job状态
    - 获取job结果
    - 获取job日志
    - 等待job完成
    """

    JOB_FINAL_STATES: tuple[JobStatus, ...] = ("DONE", "CANCELLED", "ERROR")

    def __init__(
        self,
        client: RuntimeClient,
        job_id: list[str],
        observable: Any | None = None,
        *,
        backend_name: str | None = None,
        shots: int | None = None,
        circuit_type: Literal["sampler", "estimator"] | None = None,
        num_qubits: int | None = None,
    ) -> None:
        self._status = {
            "status": "INITIALIZING",
            "error_code": 0,
        }
        self._client = client
        self._job_id = job_id
        self._observable = observable
        self._backend_name = backend_name
        self._shots = shots
        self._circuit_type = circuit_type
        self._num_qubits = num_qubits
        self._result = None

    def _validate_observable_coverage(self, evs: Any) -> None:
        observables = self._observable
        if observables is None:
            return
        if self._backend_name == "MPS" and not isinstance(observables, list):
            from .submit_payload import sparsepauliop_to_mps_observables
            observables = sparsepauliop_to_mps_observables(observables)
        if not isinstance(observables, list):
            return
        if self._backend_name in (None, "MPS") or (
            self._backend_name == "Guoji08" and self._num_qubits is not None
        ):
            if not isinstance(evs, dict):
                raise RuntimeJobFailureError("Task result missing named observable values")
            missing = {observable["name"] for observable in observables} - evs.keys()
            if missing:
                raise RuntimeJobFailureError(f"Task result missing observable values: {sorted(missing)}")
        else:
            # Hardware may encode names differently (e.g. Z instead of Z0).
            # Preserve its labels; do not invent a positional/name mapping.
            count = len(evs) if isinstance(evs, (dict, list)) else 1
            if count != len(observables):
                raise RuntimeJobFailureError(
                    f"Task result observable count mismatch: expected {len(observables)}, got {count}"
                )

    def result(
        self,
        timeout: float | None = None,
    ) -> Any:
        """返回任务的结果."""
        start_time = time.monotonic()
        deadline = None if timeout is None else start_time + timeout
        self.wait_for_final_state(timeout=timeout)
        status = self._status.get("status")
        if status == "ERROR":
            if self._status.get("error_code") == 1305:
                raise RuntimeJobTimeoutError(
                    "Job wait exceeded maximum waiting time (任务等待超过最大等待时间)"
                )
            raise RuntimeJobFailureError(
                f"Job failed (任务失败), error code (错误代码): {self._status.get('error_code')}"
            )
        if status == "CANCELLED":
            raise RuntimeJobFailureError("Job was cancelled (任务已取消)")

        for attempt in range(_RESULT_POLL_ATTEMPTS):
            try:
                return self._read_result()
            except _ResultNotReady:
                if attempt == _RESULT_POLL_ATTEMPTS - 1:
                    raise RuntimeJobFailureError(
                        "Job completed, but its result is still not available after retries "
                        "(任务已完成，但结果在重试后仍未就绪)"
                    ) from None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeJobTimeoutError(
                            f"Job completed, but the result was not available within {timeout} seconds "
                            f"(任务已完成，但结果在 {timeout} 秒内仍未就绪)"
                        ) from None
                    time.sleep(min(_RESULT_POLL_INTERVAL, remaining))
                else:
                    time.sleep(_RESULT_POLL_INTERVAL)

    def _read_result(self) -> Any:
        """Fetch and normalize one result response.

        A completed task can become visible before its result has propagated to
        the result endpoint.  Only an absent primitive result is treated as
        transient here; explicit malformed result data still fails immediately.
        """
        result = self._client.task_result(self._job_id)
        if not isinstance(result, dict):
            raise RuntimeJobFailureError(
                "Task result must be a dict (任务结果必须为字典)"
            )

        self._result = dict(result)
        nested = self._result.get("result")
        if isinstance(nested, dict) and "code" in nested:
            if nested["code"] != 200:
                raise RuntimeJobFailureError(f"Task result failed: {nested.get('msg')}")
            data = nested.get("data")
            if not isinstance(data, dict):
                raise RuntimeJobFailureError("Task result data must be a dict")
            self._result.pop("result")
            self._result.update(data)
        nested = self._result.get("result")
        if isinstance(nested, dict) and any(
            key in nested
            for key in (
                "data", "estimator_result", "counts", "probabilities", "evs",
                "freq_res", "optimize_circuit",
            )
        ):
            self._result.pop("result")
            self._result.update(nested)
        # MPS uses data for both primitives; keep older task results readable.
        result_key = "data" if "data" in self._result else "estimator_result"
        result_data = self._result.get(result_key)
        if result_key == "data" or result_data is not None:
            if not isinstance(result_data, dict):
                raise RuntimeJobFailureError(f"{result_key} must be a dict")
            self._result.update(result_data)

        counts = _counts_from_result(self._result)
        probabilities = None
        if self._backend_name == "MPS" and counts is not None:
            counts, probabilities = _normalize_mps_counts(counts, self._shots, self._num_qubits)
            if probabilities is not None:
                self._result["probabilities"] = probabilities
                self._result.pop("counts", None)
                if isinstance(result_data, dict):
                    normalized_data = dict(result_data)
                    normalized_data["probabilities"] = probabilities
                    if counts is None:
                        normalized_data.pop("counts", None)
                    else:
                        normalized_data["counts"] = counts
                    self._result[result_key] = normalized_data
        if self._backend_name == "MPS" and self._circuit_type == "sampler":
            self._result.pop("evs", None)
            if isinstance(self._result.get(result_key), dict):
                sampler_data = dict(self._result[result_key])
                sampler_data.pop("evs", None)
                self._result[result_key] = sampler_data
            has_server_evs, server_evs = False, None
        elif (
            self._backend_name == "Guoji08"
            and isinstance(self._observable, list)
            and (self._num_qubits is not None or self._circuit_type == "estimator")
            and self._result.get("evs") is not None
        ):
            from .guoji_estimator import decode_guoji_expectations

            if self._num_qubits is None:
                self._num_qubits = _guoji_result_width(self._result["evs"], self._observable)
            server_evs = decode_guoji_expectations(
                self._result["evs"], self._observable, self._num_qubits
            )
            has_server_evs = True
            if len(self._observable) > 1:
                # The cloud supplies one error for its aggregate, not one per name.
                self._result["ensemble_standard_error"] = None
        else:
            has_server_evs, server_evs = _evs_from_result(self._result)
        if server_evs is not None:
            self._result["evs"] = server_evs
        if (
            counts is None
            and not has_server_evs
            and _result_payload_is_pending(self._result)
        ):
            raise _ResultNotReady
        if has_server_evs:
            self._validate_observable_coverage(server_evs)
        elif self._observable is not None and counts is not None:
            if self._backend_name == "MPS" or isinstance(self._observable, list):
                raise RuntimeJobFailureError("Task result missing named observable values")
            self._result["evs"] = _get_expectation_value(counts, self._observable)
        elif self._observable is not None:
            raise RuntimeJobFailureError(
                "Task result missing observable values (任务结果缺少观测量结果)"
            )

        if counts is not None:
            self._result["counts"] = counts
        elif not has_server_evs:
            raise RuntimeJobFailureError(
                "Task result missing measurement counts (任务结果缺少测量计数)"
            )
        self._result.pop("result", None)
        return self._result

    def status(self) -> dict:
        """返回任务状态字典 ``{"status", "error_code"}``."""
        response = self._client.task_status(self._job_id)
        self._status["status"] = _map_task_state(
            response.get("task_state"), self._status.get("status")
        )
        self._status["error_code"] = response["error_code"]
        return self._status

    def job_log(self) -> str:
        """返回任务的执行日志."""
        return self._client.task_log(self._job_id).get("log")

    def wait_for_final_state(
        self,
        timeout: float | None = None,
    ) -> None:
        """从 API 轮询作业状态，直到状态进入最终态."""
        start_time = time.time()
        status = self._status["status"]
        while status not in self.JOB_FINAL_STATES:
            elapsed_time = time.time() - start_time
            if timeout is not None and elapsed_time >= timeout:
                self._status["status"] = "ERROR"
                self._status["error_code"] = 1305
                raise RuntimeJobTimeoutError(
                    f"Timeout occurred after waiting {timeout} seconds for the job to complete "
                    f"(在等待作业完成 {timeout} 秒后发生超时)"
                )
            time.sleep(0.1)
            response = self._client.task_status(self._job_id)
            status = _map_task_state(response.get("task_state"), status)
            self._status["status"] = status
            self._status["error_code"] = response["error_code"]
