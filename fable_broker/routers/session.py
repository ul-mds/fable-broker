from datetime import datetime, timedelta
import logging

from celery.result import AsyncResult
from fable_model.broker import (
    SessionCreationResponse,
    SessionCreationRequest,
    SessionDeletionRequest,
    SessionUpdateResponse,
    SessionUpdateRequest,
    ClientSubmissionRequest,
    ClientVectorBatch,
    VectorMatchBatch,
    ClientResultResponse,
    ClientResultRequest,
)
from fable_model.match import BaseMatchRequest
from fable_client import FableClient, FableError
from fastapi import APIRouter, status, Depends, HTTPException, Response
from neo4j import Driver
from starlette.background import BackgroundTasks

from fable_broker.config import Settings
from fable_broker.dependencies import get_settings, next_secret, get_session_mapping, get_fable_client, get_neo4j_driver
from fable_broker.internal.graph import delete_for_session, get_vector_ids_for_client, get_matches_for_client
from fable_broker.internal.state import MatchSession
from fable_broker.internal.utils import random_vector, mask_string
from fable_broker.worker.tasks import persist_client_vectors, match_and_persist


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=SessionCreationResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    req: SessionCreationRequest,
    settings: Settings = Depends(get_settings),
    session_token: str = Depends(next_secret),
    session_mapping: dict[str, MatchSession] = Depends(get_session_mapping),
    client: FableClient = Depends(get_fable_client),
):
    """
    Registers a new match session. First, validates the provided match config by sending an example request to the
    match service. If valid, constructs a new match session and registers it if it doesn't exist yet.
    """

    if req.expires_in <= 0 or req.expires_in > settings.max_session_timeout:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Field 'expires_in' must be in range of 1 to {settings.max_session_timeout}",
        )

    # Perform a sample request against the match service to check if the config is valid.
    try:
        client.match(
            BaseMatchRequest(config=req.match_config).with_vectors(
                domain_lst=[random_vector()],
                range_lst=[random_vector()],
            ),
        )
    except FableError as e:
        if e.error_type == "validation":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid match configuration")
        else:
            logger.error("Unexpected HTTP error while trying to perform test match", exc_info=True)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Unexpected response from match service")

    # Compute the expiration timestamp.
    exp_dur = timedelta(seconds=req.expires_in)
    exp_dt = datetime.now() + exp_dur
    exp_ts = int(exp_dt.timestamp())

    match_session = MatchSession(req.match_config, session_token, exp_ts)

    # Check that the session isn't already taken.
    if req.session in session_mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session already exists")

    session_mapping[req.session] = match_session

    logger.debug(f"Created new session {mask_string(req.session)}, expires at {exp_ts} ({str(exp_dur)} from now)")

    return SessionCreationResponse(session=req.session, token=session_token, expires_at=exp_ts)


async def _delete_session_async(
    req: SessionDeletionRequest,
    match_session: MatchSession,
    driver: Driver,
):
    logger.debug(f"Session cancellation requested, stopping tasks and deleting data for {mask_string(req.session)}...")

    for task in match_session.match_tasks:
        if not task.ready():
            task.revoke()

    delete_for_session(driver, req.session)


@router.delete("", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def delete_session(
    req: SessionDeletionRequest,
    background_tasks: BackgroundTasks,
    session_mapping: dict[str, MatchSession] = Depends(get_session_mapping),
    driver: Driver = Depends(get_neo4j_driver),
):
    """
    Checks whether the session that is supposed to be deleted is registered. If so, tries to match the provided
    token against the assigned session token. If equal, the session is deleted.
    """
    if req.session not in session_mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session doesn't exist")

    match_session = session_mapping[req.session]

    if match_session.token != req.token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect session token")

    del session_mapping[req.session]
    background_tasks.add_task(_delete_session_async, req, match_session, driver)

    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.patch("", response_model=SessionUpdateResponse, status_code=status.HTTP_200_OK)
async def refresh_session(
    req: SessionUpdateRequest,
    settings: Settings = Depends(get_settings),
    session_mapping: dict[str, MatchSession] = Depends(get_session_mapping),
):
    """
    Checks whether the session that is supposed to be updated is registered. If so, tries to match the provided
    token against the assigned session token. If equal, the expiration timestamp of the session is extended by
    the server-configured duration.
    """
    if req.session not in session_mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session doesn't exist")

    match_session = session_mapping[req.session]

    if match_session.token != req.token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect session token")

    exp_dt = datetime.now() + timedelta(seconds=settings.refresh_session_interval)
    exp_ts = int(exp_dt.timestamp())

    match_session.expires_at = exp_ts

    logger.debug(
        f"Refreshed session {mask_string(req.session)}, expires at {exp_ts} "
        f"({str(timedelta(seconds=settings.refresh_session_interval))} from now)"
    )

    return SessionUpdateResponse(
        session=req.session,
        expires_at=exp_ts,
    )


async def _submit_vectors_async(
    req: ClientSubmissionRequest,
    match_session: MatchSession,
    driver: Driver,
):
    logger.debug(f"Preparing {len(req.vectors)} vectors from client {mask_string(req.client)}...")

    task: AsyncResult = persist_client_vectors.delay(
        req.session,
        req.client,
        [v.model_dump() for v in req.vectors],
    )

    vector_ids: list[int] = task.get(timeout=10)

    logger.debug("Vectors persisted, fetching range vectors...")

    range_lst: list[ClientVectorBatch] = []

    for other_client in match_session.clients:
        if req.client == other_client:
            continue

        range_lst.append(
            ClientVectorBatch(client=other_client, ids=get_vector_ids_for_client(driver, req.session, other_client))
        )

    if len(range_lst) == 0:
        logger.debug("No other clients submitted vectors")
        return

    logger.debug(f"Submitting task to perform matching against {len(range_lst)} other client(s)...")

    match_session.match_tasks.append(
        match_and_persist.delay(
            VectorMatchBatch(
                domain=ClientVectorBatch(
                    client=req.client,
                    ids=vector_ids,
                ),
                range=range_lst,
                session=req.session,
                config=match_session.config,
            ).model_dump(),
        )
    )


@router.post("/submit", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def submit_vectors(
    req: ClientSubmissionRequest,
    background_tasks: BackgroundTasks,
    session_mapping: dict[str, MatchSession] = Depends(get_session_mapping),
    driver: Driver = Depends(get_neo4j_driver),
):
    """
    Submits vectors to a match session on behalf of a client. Matching will automatically commence in the background
    after the vectors have been submitted.
    """
    if req.session not in session_mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session doesn't exist")

    match_session = session_mapping[req.session]
    match_session.clients.add(req.client)

    background_tasks.add_task(_submit_vectors_async, req, match_session, driver)

    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/result", status_code=status.HTTP_200_OK, response_model=ClientResultResponse)
async def get_results(
    req: ClientResultRequest,
    session_mapping: dict[str, MatchSession] = Depends(get_session_mapping),
    driver: Driver = Depends(get_neo4j_driver),
):
    """
    Returns the match results for a client. No matches will be returned if matching hasn't concluded, unless
    explicitly specified.
    """
    if req.session not in session_mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session doesn't exist")

    match_session = session_mapping[req.session]

    if req.client not in match_session.clients:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Client hasn't submitted any vectors")

    matching_finished = True

    for task in match_session.match_tasks:
        if not task.ready():
            matching_finished = False
            break

    if not matching_finished and not req.show_unfinished_results:
        return ClientResultResponse(finished=matching_finished, matches=[])
    else:
        return ClientResultResponse(
            finished=matching_finished,
            matches=get_matches_for_client(driver, req.session, req.client),
        )
