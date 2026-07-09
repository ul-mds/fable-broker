import threading

from fastapi import status
import httpx

from fable_broker.main import config_server
from tests.helpers import assert_eventually


def test_run_server():
    host, port = "127.0.0.1", 8000
    server = config_server(host=host, port=port)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:

        def _wait_for_server_to_start():
            assert server.started

        assert_eventually(_wait_for_server_to_start)

        r = httpx.get(f"http://{host}:{port}/health")

        assert r.status_code == status.HTTP_200_OK
        assert r.json() == {"status": "ok"}
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert not thread.is_alive()
