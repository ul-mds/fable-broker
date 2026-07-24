from celery.utils.log import get_task_logger
from fable_client import PPRLClient
from fable_model.broker import MetaBitVectorEntity, VectorMatchBatch
from fable_model.match import BaseMatchRequest
from neo4j import Driver

from fable_broker.dependencies import get_settings
from fable_broker.internal.graph import connect_neo4j, insert_vectors_for_client, get_vectors_by_id, insert_matches
from fable_broker.internal.utils import mask_string
from fable_broker.worker.celery import celery_app


logger = get_task_logger(__name__)


def connect_neo4j_driver() -> Driver:
    return connect_neo4j(get_settings().neo4j_url)


@celery_app.task(name="persist_client_vectors")
def persist_client_vectors(session: str, client: str, vectors: list[dict]):
    with connect_neo4j_driver() as driver:
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
    batch = VectorMatchBatch(**raw_batch)
    # Instantiate the client here because PPRLClient is not JSON serializable.
    client = PPRLClient(base_url=get_settings().pprl_service_base_url)

    with connect_neo4j_driver() as driver:
        logger.info(
            "Fetching %d vectors for client %s...",
            len(batch.domain.ids),
            mask_string(batch.domain.client),
        )
        domain_vectors = get_vectors_by_id(driver, batch.domain.ids)

        for range_batch in batch.range:
            logger.info(
                "Fetching %d vectors for client %s...",
                len(range_batch.ids),
                mask_string(range_batch.client),
            )
            range_vectors = get_vectors_by_id(driver, range_batch.ids)

            matches = client.match(
                BaseMatchRequest(config=batch.config).with_vectors(
                    domain_lst=domain_vectors,
                    range_lst=range_vectors,
                ),
            ).matches
            logger.info("Received %d matches", len(matches))

            insert_matches(driver, batch.session, batch.domain.client, range_batch.client, matches)
