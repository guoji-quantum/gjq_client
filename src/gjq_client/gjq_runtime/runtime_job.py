"""RuntimeJob类, 实现下面的功能：
- 获取job状态
- 获取job结果
- 获取job日志
- 等待job完成
"""

from typing import Any, Literal
import logging
import time


from ..client.runtime import RuntimeClient


from ..utils.exceptions import (
    RuntimeJobFailureError,
    RuntimeJobTimeoutError,
)

logger = logging.getLogger(__name__)

def _get_expectation_value(counts, pauli_op):
    expectation = 0 
    total_shots = sum(counts.values())

    for pauli, coeff in zip(pauli_op.paulis, pauli_op.coeffs):
        pauli_label = pauli.to_label()[::-1] 
        exp_val = 0

        for b, c in counts.items():
            bitstring = b[::-1] 
            parity = sum(
                int(bitstring[i])
                for i,p in enumerate(pauli_label) if p!='I'
            ) % 2

            exp_val += ((-1)**parity) * c
        if total_shots == 0:
            exp_val = 0
        else:
            exp_val /= total_shots
        expectation += coeff * exp_val
    return expectation.real

JobStatus = Literal["INITIALIZING", "QUEUED", "RUNNING", "CANCELLED", "DONE", "ERROR"]
API_TO_JOB_STATUS: dict[str, JobStatus] = {
    "INITIALIZING": "INITIALIZING",
    "pending": "QUEUED",
    "running": "RUNNING",
    "completed": "DONE",
    "failed": "ERROR",
}


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
        obs: Any | None = None
    ) -> None:
        """
        参数:
            
            client: RuntimeClient对象.
            job_id: Job ID.
            tag: 任务类型，"sampler" 或 "estimator"，用于区分不同类型的任务，默认值为 None。
        """
        self._status={
            "status":"INITIALIZING",
            "error_code":0
        }
        self._client= client
        self._job_id = job_id
        self._obs = obs
        self._result = None

    def result( 
        self,
        timeout: float | None = None,
    ) -> Any:
        """返回任务的结果.

        Args:
            timeout: 等待任务的超时时间.

        Returns:
            任务的结果

        """
        self.wait_for_final_state(timeout=timeout)
        if self._status.get("status") == "ERROR":
            if  self._status.get("error_code") == 1305:
                raise RuntimeJobTimeoutError("Job wait exceeded maximum waiting time (任务等待超过最大等待时间)")
            raise RuntimeJobFailureError(f"Job failed (任务失败), error code (错误代码): {self._status.get('error_code')}")
        if self._obs:
            self._result= self._client.task_result(self._job_id)
            counts=self._result.get('result')
            self._result['evs']=_get_expectation_value(counts, self._obs)
            self._result['counts'] = self._result.pop('result')
            return self._result
        else:
            self._result = self._client.task_result(self._job_id)
            self._result['counts'] = self._result.pop('result')
            return self._result

    def status(self) -> JobStatus | str:
        """返回任务的状态.

        Returns:
            任务的状态(INITIALIZING, QUEUED, RUNNING, CANCELLED, DONE, ERROR).
        """
        response = self._client.task_status(self._job_id)
        self._status['status'] = API_TO_JOB_STATUS.get(response['task_state'])
        self._status['error_code'] = response['error_code']
        return self._status
    
    def job_log(self) -> str:
        """
        返回任务的执行日志.
        """
        return self._client.task_log(self._job_id).get('log')

    def wait_for_final_state(  # pylint: disable=arguments-differ
        self,
        timeout: float | None = None,
    ) -> None:
        """从 API 轮询作业状态，直到状态进入最终态

        Args:
            timeout: 等待作业完成的秒数。若为 ``None``，则无限期等待.
        """
        start_time = time.time()
        status = self._status['status']
        while status not in self.JOB_FINAL_STATES:
            elapsed_time = time.time() - start_time
            if timeout is not None and elapsed_time >= timeout:
                self._status['status'] = "ERROR"
                self._status['error_code'] = 1305
                raise RuntimeJobTimeoutError(
                    f"Timeout occurred after waiting {timeout} seconds for the job to complete (在等待作业完成 {timeout} 秒后发生超时)"
                )
            time.sleep(0.1)
            response = self._client.task_status(self._job_id)
            status = API_TO_JOB_STATUS.get(response.get('task_state'))
            self._status['status'] = status
            self._status['error_code'] = response['error_code']
