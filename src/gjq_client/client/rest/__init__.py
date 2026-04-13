# REST 适配器包
#
# URL_MAP 更新指南:
#   - 认证 API → client/rest/user_token.py 中 UserToken.URL_MAP
#   - 后端查询 API → client/rest/backend.py 中 Backend.URL_MAP / MachineBackend.URL_MAP
#   - 任务管理 API → client/rest/task.py 中 Task.URL_MAP / TaskInstance.URL_MAP

from gjq_client.client.rest.base import RestAdapterBase
from gjq_client.client.rest.user_token import UserToken
from gjq_client.client.rest.backend import Backend, MachineBackend
from gjq_client.client.rest.task import Task, TaskInstance

__all__ = [
    "RestAdapterBase",
    "UserToken",
    "Backend",
    "MachineBackend",
    "Task",
    "TaskInstance",
]
