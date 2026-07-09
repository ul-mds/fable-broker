from random import Random

from _pytest.monkeypatch import MonkeyPatch
from fable_model.broker import MatchConfig, SessionCreationRequest
from fastapi import status
from fastapi.testclient import TestClient

from fable_broker import dependencies
from fable_broker.config import Settings
from fable_broker.dependencies import get_session_mapping
from fable_broker.server import app
from tests.helpers import random_b64, assert_eventually


def test_cleanup_expired_session(
    monkeypatch: MonkeyPatch,
    rng: Random,
):
    # Override settings so that the cleanup is done more often.
    monkeypatch.setenv("TASK_CLEANUP_INTERVAL", "1")
    monkeypatch.setattr(dependencies, "get_settings", lambda: Settings())

    with TestClient(app) as test_client:
        session = random_b64(rng)

        r = test_client.post(
            "/session",
            json=SessionCreationRequest(
                session=session,
                match_config=MatchConfig(
                    measures=["jaccard"],
                    thresholds=[0.8],
                ),
                expires_in=1,
            ).model_dump(),
        )

        assert r.status_code == status.HTTP_201_CREATED

        def _check_for_cleanup():
            assert session not in get_session_mapping().keys()

        assert_eventually(_check_for_cleanup)
