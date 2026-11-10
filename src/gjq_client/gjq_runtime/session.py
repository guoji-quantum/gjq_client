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
        self._close_attempted = False
        self._closed = False

    def details(self) -> dict:
        """Return the current server-side Session details."""
        return self._api_client.session_details(self.session_id, self.backend.name)

    @property
    def status(self) -> str | None:
        """Return the current server-side Session status."""
        details = self.details()
        session_info = details.get("sessionInfo")
        if isinstance(session_info, dict):
            return session_info.get("status")
        return details.get("status")

    def tasks(self) -> list[dict]:
        """Return the tasks under this Session."""
        return self._api_client.session_tasks(self.session_id, self.backend.name)

    def close(self) -> dict:
        """Close the Session to new submissions.

        The server cancels queued jobs and lets running jobs finish. This method
        does not poll those running jobs for completion.
        """
        if self._closed:
            return self._close_result
        self._close_attempted = True
        self._close_result = self._api_client.close_session(self.session_id, self.backend.name)
        self._closed = True
        return self._close_result

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *args):
        # A failed close may have reached the server. Only explicit calls may retry.
        if not self._close_attempted:
            self.close()
