"""
异常模块 (exceptions.py)
========================

定义 gjq-client SDK 统一的异常类型体系。

异常层次结构::

    GJQRuntimeError (SDK 基础异常)
    ├── AuthenticationError          # api_key 无效或认证失败
    ├── AuthorizationError           # access_token 过期或权限不足
    ├── APIError                     # 云平台 API 返回业务错误 (code != 0)
    ├── NetworkError                 # 网络连接失败 / DNS 解析失败
    ├── GJQTimeoutError              # HTTP 请求超时 / 任务等待超时
    ├── BackendError                 # 后端通用错误
    │   ├── BackendNotFoundError     # 指定后端不存在
    │   └── BackendOfflineError      # 后端离线或不可用
    ├── JobError                     # 任务通用错误
    │   ├── JobNotFoundError         # 任务 ID 不存在
    │   ├── JobCancelledError        # 任务已被取消
    │   └── JobFailedError           # 任务执行失败
    ├── SessionError                 # Session 通用错误
    │   └── SessionClosedError       # Session 已关闭
    └── ConfigurationError           # SDK 配置参数错误

使用示例::

    from gjq_client.utils.exceptions import AuthenticationError, APIError

    try:
        client.authenticate(api_key="invalid-key")
    except AuthenticationError as e:
        print(f"认证失败: {e}")
    except APIError as e:
        print(f"API 错误 [{e.status_code}]: {e.message}")
"""

__all__ = [
    "GJQRuntimeError",
    "AuthenticationError",
    "AuthorizationError",
    "APIError",
    "NetworkError",
    "GJQTimeoutError",
    "BackendError",
    "BackendNotFoundError",
    "BackendOfflineError",
    "JobError",
    "JobNotFoundError",
    "JobCancelledError",
    "JobFailedError",
    "SessionError",
    "SessionClosedError",
    "ConfigurationError",
]


from typing import Optional


class GJQBaseError(Exception):
    """基础异常类"""

    message: Optional[str]

    def __init__(self, *message):
        """设置错误消息."""
        super().__init__(" ".join(message))
        self.message = " ".join(message)

    def __str__(self):
        """返回消息."""
        return repr(self.message)

class GJQError(GJQBaseError):
    """运行时服务模块引发错误的基础类."""

    pass


class GJQBackendError(GJQError):
    """后端模块引发错误的基础类."""

    pass


class GJQBackendApiProtocolError(GJQBackendError):
    """当从服务器接收到意外值时引发的错误."""

    pass

class InvalidChannelError(GJQBaseError):
    """无效的channel."""

    pass

class RuntimeJobTimeoutError(GJQBaseError):
    """任务等待超时."""

    pass

class RuntimeJobFailureError(GJQBaseError):
    """任务失败."""

    pass

# ==============================================================================
# 基础异常
# ==============================================================================

class GJQRuntimeError(Exception):
    """gjq-client SDK 基础异常类。

    所有 SDK 相关的异常都继承自此类，用户可以通过捕获此异常
    来统一处理所有 SDK 错误。

    Args:
        message: 错误描述信息。
    """

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(self.message)


# ==============================================================================
# 认证相关异常
# ==============================================================================

class AuthenticationError(GJQRuntimeError):
    """认证失败异常。

    当 api_key 无效、已过期或格式错误时抛出。
    对应 HTTP 401 状态码（认证接口 POST /auth/token 返回）。

    Examples::

        raise AuthenticationError("Invalid API key")
    """
    pass


class AuthorizationError(GJQRuntimeError):
    """授权失败异常。

    当 access_token 过期或用户权限不足时抛出。
    对应 HTTP 401/403 状态码（业务接口返回）。

    与 AuthenticationError 的区别:
        - AuthenticationError: api_key 本身无效（首次认证失败）
        - AuthorizationError: access_token 过期或权限不足（已认证但授权失败）
    """
    pass


# ==============================================================================
# HTTP 通信相关异常
# ==============================================================================

class APIError(GJQRuntimeError):
    """云平台 API 业务错误异常。

    当 API 返回 HTTP 200 但业务状态码 code != 0 时抛出，
    或者 HTTP 状态码为 4xx/5xx 时抛出。

    Attributes:
        message: 错误描述信息。
        status_code: HTTP 状态码（如 400, 500），可能为 None。
        response_body: API 返回的原始响应体字典，可能为 None。

    Examples::

        raise APIError(
            message="Backend not found",
            status_code=404,
            response_body={"code": 404, "message": "Backend not found", "data": None}
        )
    """

    def __init__(
        self,
        message: str = "",
        status_code: int | None = None,
        response_body: dict | None = None,
    ):
        self.status_code = status_code
        self.response_body = response_body
        # 构建包含状态码的完整错误信息
        if status_code is not None:
            full_message = f"[HTTP {status_code}] {message}"
        else:
            full_message = message
        super().__init__(full_message)


class NetworkError(GJQRuntimeError):
    """网络连接错误异常。

    当 HTTP 请求因网络原因失败时抛出，包括：
        - DNS 解析失败
        - TCP 连接被拒绝
        - SSL/TLS 证书验证失败
        - 连接被重置

    此异常通常可以通过重试恢复。
    """
    pass


class GJQTimeoutError(GJQRuntimeError):
    """超时异常。

    当以下场景超时时抛出：
        - HTTP 请求响应超时
        - 任务轮询等待超时（job.result(timeout=...)）

    注意: 使用 GJQTimeoutError 而非 TimeoutError，
    避免与 Python 内置 TimeoutError 冲突。
    """
    pass


# ==============================================================================
# Backend 相关异常
# ==============================================================================

class BackendError(GJQRuntimeError):
    """后端通用错误异常。

    当后端操作失败时抛出的基类异常。
    """
    pass


class BackendNotFoundError(BackendError):
    """后端不存在异常。

    当用户指定的 backend 名称在云平台上不存在时抛出。

    Examples::

        raise BackendNotFoundError("Backend 'nonexistent_qpu' not found")
    """
    pass


class BackendOfflineError(BackendError):
    """后端离线异常。

    当用户指定的 backend 存在但当前处于离线或维护状态时抛出。
    """
    pass


# ==============================================================================
# Job 相关异常
# ==============================================================================

class JobError(GJQRuntimeError):
    """任务通用错误异常。

    当任务操作失败时抛出的基类异常。
    """
    pass


class JobNotFoundError(JobError):
    """任务不存在异常。

    当查询的 job_id 在云平台上不存在时抛出。
    """
    pass


class JobCancelledError(JobError):
    """任务已取消异常。

    当对已取消的任务执行不兼容操作（如获取结果）时抛出。
    """
    pass


class JobFailedError(JobError):
    """任务执行失败异常。

    当任务在云端执行失败时抛出，通常包含失败原因信息。

    Examples::

        raise JobFailedError("Circuit compilation failed: invalid gate 'custom_gate'")
    """
    pass


# ==============================================================================
# Session 相关异常
# ==============================================================================

class SessionError(GJQRuntimeError):
    """Session 通用错误异常。

    当 Runtime Session 操作失败时抛出的基类异常。
    """
    pass


class SessionClosedError(SessionError):
    """Session 已关闭异常。

    当向已关闭的 Session 提交新任务时抛出。
    """
    pass


# ==============================================================================
# 配置相关异常
# ==============================================================================

class ConfigurationError(GJQRuntimeError):
    """SDK 配置错误异常。

    当 SDK 初始化参数无效或配置文件格式错误时抛出，包括：
        - api_key 缺失（未传入且环境变量/配置文件中也没有）
        - API URL 格式无效
        - 配置文件解析失败
    """
    pass
