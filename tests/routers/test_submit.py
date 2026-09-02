from random import Random
from typing import Callable

from fable_model.broker import SessionCreationResponse, ClientSubmissionRequest, SessionDeletionRequest
from fastapi import status
from fastapi.testclient import TestClient
from neo4j import Driver
from pydantic import SecretStr

from tests.helpers import random_meta_vec, assert_eventually, detail_of


def get_client_vector_count(
    graphdb_driver: Driver,
    session: str,
    client: str,
) -> int:
    with graphdb_driver.session() as s:
        vec_count = s.execute_read(
            lambda tx: tx.run(
                "MATCH (b:BitVector {session: $session, client: $client}) RETURN count(b)",
                session=session,
                client=client,
            ).single(True)[0]
        )
    return vec_count


def test_submit(
    test_client: TestClient,
    rng: Random,
    match_session: SessionCreationResponse,
    graphdb_driver: Driver,
    secret_factory: Callable[[], SecretStr],
):
    client = secret_factory()
    target_vec_count = 5

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=match_session.session,
            client=client,
            vectors=[random_meta_vec(rng) for _ in range(target_vec_count)],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    def check_vector_persist():
        assert (
            get_client_vector_count(graphdb_driver, match_session.session.get_secret_value(), client.get_secret_value())
            == target_vec_count
        )

    assert_eventually(check_vector_persist)


def test_submit_and_delete(
    test_client: TestClient,
    rng: Random,
    match_session: SessionCreationResponse,
    graphdb_driver: Driver,
    secret_factory: Callable[[], SecretStr],
):
    client = secret_factory()
    target_vec_count = 5

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=match_session.session,
            client=client,
            vectors=[random_meta_vec(rng) for _ in range(target_vec_count)],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    r = test_client.request(
        "DELETE",
        "/session",
        json=SessionDeletionRequest(
            session=match_session.session,
            token=match_session.token,
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_202_ACCEPTED

    def check_vector_empty():
        assert (
            get_client_vector_count(graphdb_driver, match_session.session.get_secret_value(), client.get_secret_value())
            == 0
        )

    assert_eventually(check_vector_empty)


def test_submit_400_on_unknown_session(
    test_client: TestClient,
    rng: Random,
    secret_factory: Callable[[], SecretStr],
):
    target_vec_count = 5

    r = test_client.post(
        "/session/submit",
        json=ClientSubmissionRequest(
            session=secret_factory(),
            client=secret_factory(),
            vectors=[random_meta_vec(rng) for _ in range(target_vec_count)],
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_of(r) == "Session doesn't exist"
