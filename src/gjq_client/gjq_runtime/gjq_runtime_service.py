

import getpass
import json
import logging
import os
import stat
import subprocess
import tempfile

from ..utils.exceptions import (
    ConfigurationError,
    GJQBackendApiProtocolError,
    InvalidChannelError,
)
from ..client.client_parameters import ClientParameters
from ..client.runtime import RuntimeClient
from typing import Any
from .runtime_job import RuntimeJob, API_TO_JOB_STATUS

logger = logging.getLogger(__name__)

_DEFAULT_ACCOUNT_CONFIG_JSON_FILE = os.path.join(
    os.path.expanduser("~"), ".gjq_client", "gjq_client_account.json"
)


def _restrict_account_file(path: str) -> None:
    """Limit an account file to its owner (plus Windows system accounts)."""
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return

    domain = os.environ.get("USERDOMAIN")
    user = getpass.getuser()
    identity = f"{domain}\\{user}" if domain else user
    command = [
        "icacls.exe",
        path,
        "/inheritance:r",
        "/grant:r",
        f"{identity}:(F)",
        "*S-1-5-18:(F)",       # Local System
        "*S-1-5-32-544:(F)",   # Built-in Administrators
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise ConfigurationError(
            "Unable to secure the account configuration file"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ConfigurationError(
            f"Unable to secure the account configuration file: {detail}"
        )


def _write_account_config(parameters: dict) -> None:
    """Write account settings atomically without exposing a permissive key file."""
    directory = os.path.dirname(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".gjq_client_account-", suffix=".tmp", dir=directory
    )
    os.close(descriptor)
    try:
        _restrict_account_file(temporary_path)
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(parameters, file, ensure_ascii=False, indent=4)
            file.write("\n")
        os.replace(temporary_path, _DEFAULT_ACCOUNT_CONFIG_JSON_FILE)
        _restrict_account_file(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE)
    except Exception:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass
        raise

class GJQRuntimeService:
    """runtime service类, 负责与云平台交互, 获取认证信息, 后端信息, 构建backend等
    args: 
        channel(str): "gjq_cloud" 或 None
        token(str): token
        url(str): url
        filename(str): filename 
    """


    def __init__(
            self,
            channel: str | None = None,
            api_key: str | None = None,
            base_url: str | None = None,
            backend_url: str | None = None,
            pqc: bool = False,
            pq_server_fingerprint: str | None = None,
        ) -> None:
            if channel not in ["gjq_cloud", None]:
                raise InvalidChannelError(f"Invalid channel: {channel}")
            if not channel:
                channel = "gjq_cloud"
            self._channel = channel
            self._api_key = api_key
            self._base_url = base_url
            self._backend_url = backend_url
            self._pqc = pqc
            self._pq_server_fingerprint = pq_server_fingerprint

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
            'pqc': self._pqc,
            'pq_server_fingerprint': self._pq_server_fingerprint,
        }
        if self._api_key is not None:
            client_parameters = ClientParameters(**parameters)
            _write_account_config(parameters)
        else:
            if not os.path.exists(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE):
                raise ConfigurationError(
                    f"Configuration file {_DEFAULT_ACCOUNT_CONFIG_JSON_FILE} not found "
                    "(没有找到配置文件), API key is required for first run "
                    "(首次运行需要输入api_key)."
                )
            try:
                with open(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE, 'r', encoding='utf-8') as f:
                    parameters = json.load(f)
                if not isinstance(parameters, dict):
                    raise ConfigurationError("Account configuration must be a JSON object")
                client_parameters = ClientParameters(**parameters)
            except ConfigurationError:
                raise
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise ConfigurationError(
                    f"Unable to load account configuration {_DEFAULT_ACCOUNT_CONFIG_JSON_FILE}"
                ) from exc
            # Migrate existing profiles to owner-only permissions on first use.
            _restrict_account_file(_DEFAULT_ACCOUNT_CONFIG_JSON_FILE)
        return client_parameters
    
    def list_backends(self) -> list[dict]:
        """获取后端列表并在命令行中以表格显示。"""
        response = self._client.list_backends()
        backends = response if isinstance(response, list) else list(response or [])
        if not backends:
            print("No available backends (当前没有可用后端)")
            return backends

        headers = ("Name", "Type", "Max qubits", "Available qubits", "Pending tasks", "Job modes")
        rows = [
            (
                str(backend.get("name", "-")),
                str(backend.get("type", "-")),
                str(backend.get("max_qubits", "-")),
                str(backend.get("available_qubits", "-")),
                str(backend.get("num_of_pending_tasks", "-")),
                ", ".join(backend.get("job_mode", [])) or "-",
            )
            for backend in backends
        ]
        widths = [
            max(len(headers[index]), *(len(row[index]) for row in rows))
            for index in range(len(headers))
        ]
        print(f"Available backends ({len(backends)}):")
        print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
        print("-+-".join("-" * width for width in widths))
        for row in rows:
            print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        return backends
    
    def backend_list(self):
        return self.list_backends()

    def _create_backend_obj(self,backend_name):
        """
        根据后端名称获取创建backend对象
        """
        from ..utils.exceptions import BackendNotFoundError
        if not any(backend.get("name") == backend_name for backend in self.list_backends()):
            raise BackendNotFoundError(f"Backend '{backend_name}' not found")
        # Do not convert configuration API failures into ``None``.  Returning
        # ``None`` hides the real fault and causes a later, misleading
        # ``backend is required`` validation error in Sampler/Estimator.
        config_dict=self._client.backend_configuration(backend_name)
        from ..utils.backend_decoder import configuration_from_server_data
        config=configuration_from_server_data(config_dict)
        if config is None:
            raise GJQBackendApiProtocolError(
                f"Backend '{backend_name}' configuration could not be decoded "
                f"(后端 '{backend_name}' 配置无法解析)"
            )
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

    def task_detail(self, task_id):
        """Return the cloud task-detail payload for ``task_id``."""
        return self._client.task_detail(task_id)

    def list_sessions(self) -> list[dict]:
        """Return the current user's pending and active Sessions."""
        return self._client.list_sessions()

    def session_detail(self, session_id: str, backend_name: str) -> dict:
        """Return Session details for ``session_id`` and ``backend_name``."""
        return self._client.session_details(session_id, backend_name)

    def session_tasks(self, session_id: str, backend_name: str) -> list[dict]:
        """Return the tasks submitted under a Session."""
        return self._client.session_tasks(session_id, backend_name)
    
    def task_result(self, task_id, observable: Any = None):
        """
        获取任务结果
        """ 
        status=self.task_status(task_id)
        if status in ["INITIALIZING", "QUEUED", "RUNNING"]:
            print(f"Task {task_id} is running (正在运行中), status (状态): {status}")
            return {}
        if status == "ERROR":
            print(f"Task {task_id} execution failed (任务执行失败), error code (错误代码): {self._client.task_status(task_id).get('error_code')}")
            return {}
        if status == "DONE":
            if observable is not None and not isinstance(observable, list):
                from qiskit.quantum_info import SparsePauliOp

                observable = SparsePauliOp(observable)
            detail = self._client.task_detail(task_id)
            context = {}
            if isinstance(detail, dict):
                context = {
                    "backend_name": detail.get("backend_name"),
                    "shots": detail.get("shots"),
                }
            if observable is not None:
                context["circuit_type"] = "estimator"
                if context.get("backend_name") == "Guoji08" and not isinstance(observable, list):
                    from .submit_payload import sparsepauliop_to_mps_observables

                    observable = sparsepauliop_to_mps_observables(observable)
            job = RuntimeJob(self._client, task_id, observable, **context)
            result=job.result()
            if observable is not None or ("evs" in result and "counts" not in result):
                return result.get('evs')
            else:
                return result.get('counts')
