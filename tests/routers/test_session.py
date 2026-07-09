from datetime import datetime
from random import Random

from fable_model.broker import (
    SessionCreationRequest,
    SessionCreationResponse,
    SessionDeletionRequest,
    SessionUpdateResponse,
    SessionUpdateRequest,
)
from fable_model.match import MatchConfig
from fastapi import status
from fastapi.testclient import TestClient

from tests.helpers import random_b64, detail_of, assert_eventually


def test_create(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard", "cosine", "roger_tanimoto"],
                thresholds=[0.9],
                aggregator="min",
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    j = SessionCreationResponse(**r.json())

    assert j.session == session
    assert j.expires_at > int(datetime.now().timestamp())
    assert len(j.token) > 0


def test_create_400_on_non_positive_expiration(
    test_client: TestClient,
    rng: Random,
):
    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=random_b64(rng),
            match_config=MatchConfig(
                measures=["jaccard", "dice"],
                thresholds=[0.9, 0.8],
            ),
            expires_in=0,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Field 'expires_in' must be in range of 1 to 3600"


def test_create_400_on_expiration_too_high(
    test_client: TestClient,
    rng: Random,
):
    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=random_b64(rng),
            match_config=MatchConfig(
                measures=["jaccard", "dice"],
                thresholds=[0.9, 0.8],
            ),
            expires_in=3601,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Field 'expires_in' must be in range of 1 to 3600"


def test_create_400_on_session_exists(
    test_client: TestClient,
    rng: Random,
):
    req = SessionCreationRequest(
        session=random_b64(rng),
        match_config=MatchConfig(
            measures=["jaccard"],
            thresholds=[0.8],
        ),
    )

    r = test_client.post("/session/", json=req.model_dump())

    assert r.status_code == status.HTTP_201_CREATED

    r = test_client.post("/session/", json=req.model_dump())

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Session already exists"


def test_delete(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    token = SessionCreationResponse(**r.json()).token

    r = test_client.request(
        "DELETE",
        "/session/",
        json=SessionDeletionRequest(
            session=session,
            token=token,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED


def test_delete_400_on_delete_invalid_session(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    token = SessionCreationResponse(**r.json()).token

    r = test_client.request(
        "DELETE",
        "/session/",
        json=SessionDeletionRequest(
            session=session + "123",
            token=token,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Session doesn't exist"


def test_delete_401_on_unauthorized_delete(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED
    token = SessionCreationResponse(**r.json()).token

    r = test_client.request(
        "DELETE",
        "/session/",
        json=SessionDeletionRequest(
            session=session,
            token=token + "foobar",
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_401_UNAUTHORIZED
    assert detail_of(r) == "Incorrect session token"


def test_update(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    resp = SessionCreationResponse(**r.json())
    token = resp.token
    expires_ts = resp.expires_at

    def _test_for_update():
        r = test_client.patch(
            "/session/",
            json=SessionUpdateRequest(
                session=session,
                token=token,
            ).model_dump(),
        )

        assert r.status_code == status.HTTP_200_OK

        resp = SessionUpdateResponse(**r.json())

        assert resp.session == session
        assert resp.expires_at > expires_ts

    assert_eventually(_test_for_update)


def test_update_400_on_invalid_session(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    resp = SessionCreationResponse(**r.json())
    token = resp.token

    r = test_client.patch(
        "/session/",
        json=SessionUpdateRequest(
            session=session + "123",
            token=token,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Session doesn't exist"


def test_update_401_on_unauthorized_patch(
    test_client: TestClient,
    rng: Random,
):
    session = random_b64(rng)

    r = test_client.post(
        "/session/",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=["jaccard"],
                thresholds=[0.9],
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    resp = SessionCreationResponse(**r.json())
    token = resp.token

    r = test_client.patch(
        "/session/",
        json=SessionUpdateRequest(
            session=session,
            token=token + "foobar",
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_401_UNAUTHORIZED
    assert detail_of(r) == "Incorrect session token"
