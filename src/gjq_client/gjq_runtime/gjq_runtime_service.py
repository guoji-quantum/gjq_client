

import logging
from ..utils.exceptions import InvalidChannelError
from ..client.client_parameters import ClientParameters
from ..client.runtime import RuntimeClient
from typing import Any
from .runtime_job import RuntimeJob, API_TO_JOB_STATUS

import os
import json

logger = logging.getLogger(__name__)

_DEFAULT_ACCOUNT_CONFIG_JSON_FILE = os.path.join(
    os.path.expanduser("~"), ".gjq_client", "gjq_client_account.json"
)

class GJQRuntimeService:
    """runtime service类, 负责与云平台交互, 获取认证信息, 后端信息, 构建backend等
    args: 
        channel(str): "gjq_cloud" 或 "local" 或None, Local 表示使用本地模拟器
        token(str): token
        url(str): url
        filename(str): filename 
    """


    def __init__(
            self,
            channel: str | None = None,
            api_key: str | None = None,
            base_url: str | None = None,
            backend_url: str | None = None
        ) -> None:
            if channel not in ["gjq_cloud", "local", None]:
                raise InvalidChannelError(f"Invalid channel: {channel}")
            if not channel:
                channel = "gjq_cloud"
            self._channel = channel
            self._api_key = api_key
            self._base_url = base_url
            self._backend_url = backend_url

            self._client_params=self._discover_account_info()
            self._client = RuntimeClient(self._client_params)
    
    def _discover_account_info(self) -> ClientParameters:
        """
        构造ClientParameters对象, 如果api_key为空, 则从文件中获取账号信息
        """
        parameters={
            'channel': self._channel,
            'api_key': self._api_key,
            'base_url': self._base_url,
            'backend_url': self._backend_url,
        }
        if self._api_key:
            os.makedirs(os.path.dirname(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE), exist_ok=True)
            with open(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(parameters, f, ensure_ascii=False, indent=4)
        else:
            if not os.path.exists(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE):
                raise FileNotFoundError(f"Configuration file {_DEFAULT_ACCOUNT_CONFIG_JSON_FILE} not found (没有找到配置文件), API key is required for first run (首次运行需要输入api_key).")
            with open(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE, 'r', encoding='utf-8') as f:
                parameters = json.load(f)
        return ClientParameters(**parameters)
    
    def list_backends(self):
        """
        获取后端列表
        """
        return self._client.list_backends()
    
    def backend_list(self):
        return self.list_backends()

    def _create_backend_obj(self,backend_name):
        """
        根据后端名称获取创建backend对象
        """
        from ..utils.exceptions import BackendNotFoundError
        if not any(backend.get("name") == backend_name for backend in self.list_backends()):
            raise BackendNotFoundError(f"Backend '{backend_name}' not found")
        try:
            config_dict=self._client.backend_configuration(backend_name)
            from ..utils.backend_decoder import configuration_from_server_data
            config=configuration_from_server_data(config_dict)
        except BackendNotFoundError:
            raise
        except Exception as e:
            logger.warning(f"Failed to get backend information (无法获取后端信息), root cause (原因是): {e}, please check if the backend name is correct (请检查后端名称是否正确)")
            return None
        from ..backend.gjq_backend import GJQBackend
        return GJQBackend(config,self,self._client)

    def backend(self,backend_name):
        return self._create_backend_obj(backend_name)

    def least_busy(self):
        """
        获取最空闲的后端
        """
        from ..utils.exceptions import BackendNotFoundError
        backends=self.list_backends()
        if not backends:
            raise BackendNotFoundError("No quantum backends available (当前没有可用的量子后端) (may all be under maintenance (可能全部处于维护状态))")
        backends.sort(key=lambda x: x['num_of_pending_tasks'])
        least_busy_backend_name=backends[0]['name']
        return self._create_backend_obj(least_busy_backend_name)
    
    def list_tasks(self):
        """
        获取当前用户的正在运行的任务列表
        """
        return self._client.task_list()
    
    def task_status(self,task_id):
        """
        获取任务状态
        """
        response=self._client.task_status(task_id)
        error_code=response.get("error_code")
        if error_code != 0:
            print(f"Failed to get task status (获取任务状态失败), error code (错误代码): {error_code}")
        else:
            return API_TO_JOB_STATUS.get(response.get("task_state"))
    
    def task_result(self, task_id, obs: Any = None):
        """
        获取任务结果
        """ 
        job=RuntimeJob(self._client,task_id,obs)
        status=self.task_status(task_id)
        if status in ["INITIALIZING", "QUEUED", "RUNNING"]:
            print(f"Task {task_id} is running (正在运行中), status (状态): {status}")
            return {}
        if status == "ERROR":
            print(f"Task {task_id} execution failed (任务执行失败), error code (错误代码): {self._client.task_status(task_id).get('error_code')}")
            return {}
        if status == "DONE":
            result=job.result()
            if obs:
                return result.get('evs')
            else:
                return result.get('counts')
