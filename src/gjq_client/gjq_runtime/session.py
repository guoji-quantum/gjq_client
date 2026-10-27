"""Session client object."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..backend.gjq_backend import GJQBackend
    from ..client.runtime import RuntimeClient


class Session:
    """Client-side handle for a server-managed Session."""

    def __init__(self, backend: "GJQBackend", max_time: int | None = None):
        if backend is None:
            raise ValueError("backend is required")

        self.backend = backend
        self._api_client: "RuntimeClient" = backend._api_client

        response = self._api_client.create_session(backend.name, max_time)
        self.session_id = response.get("session_id")
        if not self.session_id:
            raise RuntimeError("Session creation failed (创建 Session 失败)")
        self._closed = False

    def details(self) -> dict:
        """Return the current server-side Session details."""
        return self._api_client.session_details(self.session_id, self.backend.name)

    @property
    def status(self) -> str | None:
        """Return the current server-side Session status."""
        return self.details().get("status")

    def tasks(self) -> list[dict]:
        """Return the tasks under this Session."""
        return self._api_client.session_tasks(self.session_id, self.backend.name)

    def close(self) -> dict:
        """Close the Session."""
        if self._closed:
            return {"session_id": self.session_id, "status": "closed"}
        result = self._api_client.close_session(self.session_id, self.backend.name)
        self._closed = True
        return result

    def cancel(self) -> dict:
        """Cancel the Session."""
        if self._closed:
            # 云平台 cancel 实测终态为 closed（与 close 相同）
            return {"session_id": self.session_id, "status": "closed"}
        result = self._api_client.cancel_session(self.session_id, self.backend.name)
        self._closed = True
        return result

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *args):
        if not self._closed:
            self.close()
