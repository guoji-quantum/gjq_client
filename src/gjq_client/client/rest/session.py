"""
Session resource adapter.
"""

import requests

from gjq_client.client.rest.base import RestAdapterBase

__all__ = ["Session"]


class Session(RestAdapterBase):
    """Session management resource adapter."""

    URL_MAP = {
        "sessions": "/v1/guojisdk/sessions",
    }

    def create(self, payload: dict) -> requests.Response:
        """Create a Session."""
        return self.session.request("POST", self.get_url("sessions"), json=payload)

    def detail(self, session_id: str, backend_name: str) -> requests.Response:
        """Get Session details."""
        return self.session.request(
            "GET",
            f"{self.get_url('sessions')}/{session_id}",
            params={"backend_name": backend_name},
        )

    def list_sessions(self) -> requests.Response:
        """List current user's pending or active Sessions."""
        return self.session.request("GET", self.get_url("sessions"))

    def tasks(self, session_id: str, backend_name: str) -> requests.Response:
        """List tasks under a Session."""
        return self.session.request(
            "GET",
            f"{self.get_url('sessions')}/{session_id}/tasks",
            params={"backend_name": backend_name},
        )

    def update_status(
        self, session_id: str, backend_name: str, status: str
    ) -> requests.Response:
        """Update a Session status."""
        return self.session.request(
            "PATCH",
            f"{self.get_url('sessions')}/{session_id}",
            params={"backend_name": backend_name},
            json={"status": status},
        )
