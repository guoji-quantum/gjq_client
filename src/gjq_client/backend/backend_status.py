
import html
from typing import Any, TypeVar

from ..utils.exceptions import GJQBaseError

BackendStatusT = TypeVar("BackendStatusT", bound="BackendStatus")


class BackendStatus:
    """表示后端状态的类."""

    def __init__(
        self,
        backend_name: str,
        backend_version: str,
        operational: bool,
        pending_jobs: int,
        status_msg: str,
    ):
        """创建一个 BackendStatus 对象

        参数:
            backend_name: 后端的名称
            backend_version: 后端的版本，格式为 X.Y.Z
            operational: 如果后端可用则为 True
            pending_jobs: 后端上挂起的作业数量
            status_msg: 后端的状态信息

        异常:
            GJQBaseError: 如果后端版本格式无效则抛出
        """
        self.backend_name = backend_name
        self.backend_version = backend_version
        self.operational = operational
        if pending_jobs < 0:
            raise GJQBaseError("Pending jobs must be >=0")
        self.pending_jobs = pending_jobs
        self.status_msg = status_msg

    @classmethod
    def from_dict(cls: type[BackendStatusT], data: dict[str, Any]) -> BackendStatusT:
        """从字典创建新的 BackendStatus 对象.

        参数:
            data (dict): 表示要创建的 BaseBackend 的字典。它的格式与 :func:`to_dict` 的输出相同。

        返回:
            BackendStatus: 从输入字典创建的 BackendStatus。
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """以字典形式返回 BackendStatus 的表示.

        返回:
            dict: QobjHeader 的字典表示。
        """
        return self.__dict__

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, BackendStatus):
            if self.__dict__ == other.__dict__:
                return True
        return False

    def _repr_html_(self) -> str:
        """返回对象的 HTML 表示

        返回:
            在 Jupyter notebook 和其他调用该方法的 IDE 中使用的表示

        """
        rpr = repr(self)
        html_code = (
            f"<pre>{html.escape(rpr)}</pre>"
            f"<b>name</b>: {self.backend_name}<br/>"
            f"<b>version</b>: {self.backend_version},"
            f" <b>pending jobs</b>: {self.pending_jobs}<br/>"
            f"<b>status</b>: {self.status_msg}<br/>"
        )

        return html_code
