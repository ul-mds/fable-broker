from random import Random

from _pytest.monkeypatch import MonkeyPatch
from fable_model.broker import (
    SessionCreationResponse,
    ClientSubmissionRequest,
    ClientResultRequest,
    ClientResultResponse,
    MatchedClientVector,
)
from fastapi.testclient import TestClient
from fastapi import status

from fable_broker.dependencies import get_session_mapping
from tests.helpers import random_b64, random_meta_vec, assert_eventually, detail_of


def test_result(
    test_client: TestClient,
    rng: Random,
    match_session: SessionCreationResponse,
):
    client = random_b64(rng)
    vector = random_meta_vec(rng)

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=match_session.session,
            client=client,
            vectors=[vector],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=match_session.session,
            client=random_b64(rng),
            vectors=[vector],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    def _fetch_result():
        """Attempts to fetch results from the API. Raises an AssertionError if it has not finished yet."""
        r = test_client.post(
            "/session/result",
            json=ClientResultRequest(
                session=match_session.session,
                client=client,
            ).model_dump(),
        )

        assert r.status_code == status.HTTP_200_OK

        resp = ClientResultResponse(**r.json())

        assert resp.finished
        assert resp.matches == [
            MatchedClientVector(
                vector=vector,
                similarities=[1, 1],
                aggregated_similarity=1,
                reference_metadata=vector.metadata,
            )
        ]

    assert_eventually(_fetch_result)


def test_unfinished_matching(
    monkeypatch: MonkeyPatch,
    test_client: TestClient,
    rng: Random,
    match_session: SessionCreationResponse,
):
    session = get_session_mapping()[match_session.session]
    client = random_b64(rng)

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=match_session.session,
            client=client,
            vectors=[random_meta_vec(rng)],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    class UnfinishedTask:
        @staticmethod
        def ready():
            return False

        def revoke(self): ...

    monkeypatch.setattr(session, "match_tasks", [UnfinishedTask()])

    r = test_client.post(
        "/session/result",
        json=ClientResultRequest(
            session=match_session.session,
            client=client,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_200_OK, r.text

    resp = ClientResultResponse(**r.json())

    assert not resp.finished
    assert resp.matches == []


def test_400_on_invalid_session(
    test_client: TestClient,
    rng: Random,
):
    r = test_client.post(
        "/session/result",
        json=ClientResultRequest(
            session=random_b64(rng),
            client=random_b64(rng),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Session doesn't exist"


def test_400_on_no_submitted_vectors(
    test_client: TestClient,
    rng: Random,
    match_session: SessionCreationResponse,
):
    r = test_client.post(
        "/session/result",
        json=ClientResultRequest(
            session=match_session.session,
            client=random_b64(rng),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Client hasn't submitted any vectors"
