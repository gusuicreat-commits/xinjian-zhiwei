"""Real local sockets decide NOT_SENT vs OUTCOME_UNKNOWN by send phase, not by exception name.

A mocked httpx.ConnectTimeout never reaches the client in practice: the whole-call
deadline fires first. These servers reproduce both phases over real connections.
"""

import socket
import threading
import time

import pytest

from app.ai.clients import (
    OpenAICompatibleClient,
    ProviderOutcomeUnknown,
    ProviderTemporaryFailure,
)


def _client(base_url, timeout=0.5):
    return OpenAICompatibleClient(
        provider="openai-compatible",
        base_url=base_url,
        model="synthetic-model",
        api_key="synthetic-key",
        timeout_seconds=timeout,
        max_retries=0,
        max_output_tokens=16,
    )


def _call(client):
    return client.complete_json_once(system_prompt="Return JSON.", user_prompt="{}")


@pytest.fixture(autouse=True)
def no_system_proxy(monkeypatch):
    # macOS system proxy settings (e.g. a local Clash proxy) would otherwise
    # route these loopback requests through a proxy; env vars take precedence.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


@pytest.fixture
def server():
    """Accepts connections; behavior chosen per test. Records received bytes."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    state = {"received": b"", "mode": "silent", "stop": False, "conns": []}

    def serve():
        listener.settimeout(0.1)
        while not state["stop"]:
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            state["conns"].append(conn)
            conn.settimeout(0.1)
            deadline = time.monotonic() + 3
            while not state["stop"] and time.monotonic() < deadline:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    continue
                if not chunk:
                    break
                state["received"] += chunk
                if state["mode"] == "proxy" and chunk.startswith(b"CONNECT "):
                    # Tunnel established, then silence: TLS to the provider never completes.
                    conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                # Otherwise "silent": read everything, never answer.

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1], state
    state["stop"] = True
    thread.join(2)
    for conn in state["conns"]:
        conn.close()
    listener.close()


def test_tls_handshake_timeout_is_not_sent(server):
    port, state = server
    # https to a plain silent socket: TLS never completes, so no HTTP request is written.
    with pytest.raises(ProviderTemporaryFailure) as exc:
        _call(_client(f"https://127.0.0.1:{port}/v1"))
    assert exc.value.code == "NOT_SENT"
    assert exc.value.retryable is True and exc.value.outcome_unknown is False
    assert b"POST" not in state["received"]


def test_timeout_after_request_written_is_outcome_unknown(server):
    port, state = server
    with pytest.raises(ProviderOutcomeUnknown) as exc:
        _call(_client(f"http://127.0.0.1:{port}/v1"))
    assert exc.value.code == "OUTCOME_UNKNOWN"
    assert exc.value.retryable is False and exc.value.outcome_unknown is True
    deadline = time.monotonic() + 1
    while b"POST /v1/chat/completions" not in state["received"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert b"POST /v1/chat/completions" in state["received"]


def test_connection_refused_is_not_sent():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens here now
    with pytest.raises(ProviderTemporaryFailure) as exc:
        _call(_client(f"http://127.0.0.1:{port}/v1"))
    assert exc.value.code == "NOT_SENT"


def test_proxy_connect_tunnel_is_setup_not_send(server, monkeypatch):
    """Through an HTTP proxy, CONNECT headers are written before any provider request."""
    port, state = server
    state["mode"] = "proxy"
    monkeypatch.delenv("NO_PROXY")
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")
    with pytest.raises(ProviderTemporaryFailure) as exc:
        _call(_client("https://provider.invalid/v1"))
    assert exc.value.code == "NOT_SENT"
    assert state["received"].startswith(b"CONNECT provider.invalid:443")
    assert b"POST" not in state["received"]
