from celery.utils.log import get_task_logger
from celery.signals import worker_process_init, worker_process_shutdown
from fable_client import PPRLClient
from fable_model.broker import MetaBitVectorEntity, VectorMatchBatch
from fable_model.match import BaseMatchRequest
from neo4j import Driver

from fable_broker.config import Settings
from fable_broker.internal.graph import connect_neo4j, insert_vectors_for_client, get_vectors_by_id, insert_matches
from fable_broker.internal.utils import mask_string
from fable_broker.worker.celery import celery_app


logger = get_task_logger(__name__)

neo4j_driver: Driver | None = None
pprl_client: PPRLClient | None = None


@worker_process_init.connect
def init_worker(**_):
    global neo4j_driver, pprl_client

    neo4j_driver = connect_neo4j(Settings().neo4j_url)
    pprl_client = PPRLClient(base_url=Settings().pprl_service_base_url)


@worker_process_shutdown.connect
def shutdown_worker(**_):
    global neo4j_driver, pprl_client

    if neo4j_driver is not None:
        neo4j_driver.close()
        neo4j_driver = None

    if pprl_client is not None:
        pprl_client.close()
        pprl_client = None


def get_neo4j_driver() -> Driver:
    if neo4j_driver is None:
        raise RuntimeError("Neo4j driver has not been initialized.")
    return neo4j_driver


def get_pprl_client() -> PPRLClient:
    if pprl_client is None:
        raise RuntimeError("PPRL client has not been initialized.")
    return pprl_client


@celery_app.task(name="persist_client_vectors")
def persist_client_vectors(session: str, client: str, vectors: list[dict]):
    driver = get_neo4j_driver()

    logger.info("Storing %d vectors for client %s...", len(vectors), mask_string(client))
    vector_ids = insert_vectors_for_client(
        driver,
        session,
        client,
        [MetaBitVectorEntity(**v) for v in vectors],
    )

    return vector_ids


@celery_app.task(name="match_and_persist")
def match_and_persist(raw_batch: dict):
    driver = get_neo4j_driver()
    client = get_pprl_client()

    batch = VectorMatchBatch(**raw_batch)

    logger.info(
        "Fetching %d vectors for client %s...",
        len(batch.domain.ids),
        mask_string(batch.domain.client.get_secret_value()),
    )
    domain_vectors = get_vectors_by_id(driver, batch.domain.ids)

    for range_batch in batch.range:
        logger.info(
            "Fetching %d vectors for client %s...",
            len(range_batch.ids),
            mask_string(range_batch.client.get_secret_value()),
        )
        range_vectors = get_vectors_by_id(driver, range_batch.ids)

        matches = client.match(
            BaseMatchRequest(config=batch.config).with_vectors(
                domain_lst=domain_vectors,
                range_lst=range_vectors,
            ),
        ).matches
        logger.info("Received %d matches", len(matches))

        insert_matches(
            driver,
            batch.session.get_secret_value(),
            batch.domain.client.get_secret_value(),
            range_batch.client.get_secret_value(),
            matches,
        )
