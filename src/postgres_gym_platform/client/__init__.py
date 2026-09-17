from __future__ import annotations

from typing import Any

import httpx2


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_failed"):
        super().__init__(message)
        self.status = status
        self.code = code


class JobError(Exception):
    """A remote job finished without succeeding."""


class Client:
    def __init__(self, url: str, token: str = "", timeout: float = 60):
        self.http = httpx2.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": "Bearer " + token} if token else {},
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.http.request(method, "/api/v1" + path, **kwargs)
        if not response.is_success:
            try:
                error = response.json()["error"]
                message, code = error["message"], error["code"]
            except (ValueError, KeyError, TypeError):
                message = f"API returned HTTP {response.status_code}"
                code = "request_failed"
            raise ApiError(response.status_code, message, code)
        return response.json()

    def close(self) -> None:
        self.http.close()


__all__ = ["ApiError", "Client", "JobError"]
