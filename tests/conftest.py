import os
from random import Random
from typing import Iterator

from fable_model.broker import (
    SessionCreationResponse,
    SessionCreationRequest,
    SessionDeletionRequest,
)
from fable_model.match import MatchConfig, SimilarityMeasure, SimilarityAggregator
from fastapi.testclient import TestClient
import pytest
from neo4j import Driver
from starlette import status

from fable_broker.server import app
from fable_broker.worker.celery import celery_app
from fable_broker.worker.tasks import init_worker, shutdown_worker, get_neo4j_driver, get_pprl_client
from tests.helpers import random_b64, detail_of


@pytest.fixture(scope="session")
def pprl_service_base_url() -> str:
    return os.getenv("PPRL_SERVICE_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def amqp_url() -> str:
    return os.getenv("AMQP_URL", "amqp://guest:guest@localhost:5672//")


@pytest.fixture(scope="session")
def neo4j_url() -> str:
    return os.getenv("NEO4J_URL", "bolt://localhost:7687")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def rng() -> Random:
    return Random(42)


@pytest.fixture(scope="session")
def test_client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def graphdb_driver(test_client) -> Iterator[Driver]:
    driver = test_client.app.state.app_state.neo4j_driver

    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")

    yield driver

    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")


@pytest.fixture(scope="session", autouse=True)
def eager_celery_worker():
    # So that the task function is executed directly in the calling process. No worker needs to be started.
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,  # Exceptions in tasks raise immediately.
    )

    with pytest.raises(RuntimeError) as e:
        get_neo4j_driver()

    assert str(e.value) == "Neo4j driver has not been initialized."

    with pytest.raises(RuntimeError) as e:
        get_pprl_client()

    assert str(e.value) == "PPRL client has not been initialized."

    init_worker()

    yield

    shutdown_worker()

    # Reset since it is a global config.
    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
    )


@pytest.fixture
def match_session(test_client: TestClient, rng: Random) -> Iterator[SessionCreationResponse]:
    session = random_b64(rng)

    r = test_client.post(
        "/session",
        json=SessionCreationRequest(
            session=session,
            match_config=MatchConfig(
                measures=[SimilarityMeasure.jaccard, SimilarityMeasure.dice],
                thresholds=[0.8],
                aggregator=SimilarityAggregator.avg,
            ),
        ).model_dump(),
    )

    assert r.status_code == status.HTTP_201_CREATED

    response = SessionCreationResponse(**r.json())

    yield response

    r = test_client.request(
        "DELETE",
        "/session",
        json=SessionDeletionRequest(session=session, token=response.token).model_dump(),
    )

    match r.status_code:
        case status.HTTP_202_ACCEPTED:
            return
        case status.HTTP_400_BAD_REQUEST:
            assert detail_of(r) == "Session doesn't exist"
        case _:
            raise AssertionError(f"Unexpected status code {r.status_code}: {r.text}")
