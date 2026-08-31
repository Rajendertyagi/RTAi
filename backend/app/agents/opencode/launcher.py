"""Launch plan for an app-owned OpenCode headless server.

The server binds to 127.0.0.1 only, on a dynamically chosen private port.
Basic-auth credentials are generated per launch and passed to the child via
environment - never on the command line. The parent sends the matching
Authorization header on every request.
"""

from __future__ import annotations

import secrets
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerLaunchPlan:
    argv: tuple[str, ...]
    port: int
    hostname: str
    base_url: str
    env_overrides: dict[str, str]
    username: str
    password: str

    @property
    def auth_header(self) -> dict[str, str]:
        import base64

        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}


def pick_private_port(hostname: str = "127.0.0.1") -> int:
    """Ask the OS for a free ephemeral port, then release it for the child."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((hostname, 0))
        return int(sock.getsockname()[1])


def build_launch_plan(
    opencode_bin: str,
    *,
    hostname: str = "127.0.0.1",
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
) -> ServerLaunchPlan:
    """Build argv/env for `opencode serve` bound to loopback on a private port."""
    resolved_port = port if port is not None else pick_private_port(hostname)
    generated_password = secrets.token_urlsafe(24)
    resolved_user = username or "opencode"
    resolved_pass = password or generated_password
    return ServerLaunchPlan(
        argv=(opencode_bin, "serve", "--hostname", hostname, "--port", str(resolved_port)),
        port=resolved_port,
        hostname=hostname,
        base_url=f"http://{hostname}:{resolved_port}",
        env_overrides={
            "OPENCODE_SERVER_USERNAME": resolved_user,
            "OPENCODE_SERVER_PASSWORD": resolved_pass,
        },
        username=resolved_user,
        password=resolved_pass,
    )
