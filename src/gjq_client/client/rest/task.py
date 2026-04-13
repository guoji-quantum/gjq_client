"""
量子计算任务管理适配器 (task.py)
=================================

封装后端查询服务上的任务管理 API:
    - Task: 根适配器，管理任务提交、列表和工厂方法
    - TaskInstance: 子资源适配器，管理单个任务的状态、结果、详情、日志

使用示例::

    session = RetrySession(base_url="backend_url", auth=auth)
    task_api = Task(session)

    # 提交任务
    resp = task_api.submit(payload)

    # 查询单个任务
    instance = task_api.task_instance("abc-123")
    status_resp = instance.status()
    result_resp = instance.result()
"""

import requests

from gjq_client.client.rest.base import RestAdapterBase

__all__ = ["Task", "TaskInstance"]


class Task(RestAdapterBase):
    """任务管理根适配器。

    管理任务提交、用户任务列表和 TaskInstance 子适配器的创建。

    URL_MAP:
        submit -> /v1/guojisdk/submitTask
        list   -> /v1/guojisdk/getTaskList
    """

    URL_MAP = {
        "submit": "/v1/guojisdk/submitTask",
        "list": "/v1/guojisdk/getTaskList",
    }

    def submit(self, payload: dict) -> requests.Response:
        """提交量子计算任务。

        POST /v1/guojisdk/submitTask

        Args:
            payload: 任务提交数据，包含 device_name, quantum-num,
                     repetitions, steps 等字段。

        Returns:
            原始 requests.Response 对象。
        """
        url = self.get_url("submit")
        return self.session.request("POST", url, json=payload)

    def list_tasks(self) -> requests.Response:
        """获取当前用户的任务状态列表。

        GET /v1/guojisdk/getTaskList

        Returns:
            原始 requests.Response 对象。
        """
        url = self.get_url("list")
        return self.session.request("GET", url)

    def task_instance(self, instance_id: str) -> "TaskInstance":
        """创建指定任务的子资源适配器。

        Args:
            instance_id: 任务实例 ID（submitTask 返回的 instanceId）。

        Returns:
            TaskInstance 子适配器实例。
        """
        return TaskInstance(self.session, instance_id)


class TaskInstance(RestAdapterBase):
    """单个任务实例子资源适配器。

    封装特定任务实例的状态、结果、详情、日志查询接口。

    URL_MAP:
        status -> /v1/guojisdk/getTaskState
        result -> /v1/guojisdk/getTaskResult
        detail -> /v1/guojisdk/getTaskDetail
        log    -> /v1/guojisdk/getTaskLog
    """

    URL_MAP = {
        "status": "/v1/guojisdk/getTaskState",
        "result": "/v1/guojisdk/getTaskResult",
        "detail": "/v1/guojisdk/getTaskDetail",
        "log": "/v1/guojisdk/getTaskLog",
    }

    def __init__(self, session, instance_id: str):
        super().__init__(session)
        self._instance_id = instance_id

    def status(self) -> requests.Response:
        """查询任务状态。

        GET /v1/guojisdk/getTaskState/{instanceId}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['status']}/{self._instance_id}"
        return self.session.request("GET", url)

    def result(self) -> requests.Response:
        """获取任务执行结果。

        GET /v1/guojisdk/getTaskResult/{instanceId}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['result']}/{self._instance_id}"
        return self.session.request("GET", url)

    def detail(self) -> requests.Response:
        """获取任务详细信息。

        GET /v1/guojisdk/getTaskDetail/{instanceId}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['detail']}/{self._instance_id}"
        return self.session.request("GET", url)

    def log(self) -> requests.Response:
        """获取任务执行日志。

        GET /v1/guojisdk/getTaskLog/{instanceId}

        Returns:
            原始 requests.Response 对象。
        """
        url = f"{self.URL_MAP['log']}/{self._instance_id}"
        return self.session.request("GET", url)
