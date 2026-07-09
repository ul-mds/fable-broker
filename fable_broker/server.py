from contextlib import asynccontextmanager
from datetime import datetime
import logging
from typing import AsyncIterator

from fable_broker.dependencies import get_settings, get_session_mapping
from fable_broker.routers import session
from fastapi import FastAPI
from fastapi_utils.tasks import repeat_every

from fable_broker.internal.graph import connect_neo4j, delete_all, delete_for_session
from fable_broker.internal.utils import mask_string


logger = logging.getLogger(__name__)
expose_docs = get_settings().expose_docs


@repeat_every(seconds=get_settings().task_cleanup_interval, wait_first=True)
def free_session_tasks():
    logger.debug("Running session cleanup task...")
    now = datetime.now().timestamp()

    sessions_to_clear: list[str] = []

    # First pass: Clear match sessions if necessary.
    for ses, match_session in get_session_mapping().items():
        if now > match_session.expires_at:
            sessions_to_clear.append(ses)

    # Check because we don't want to create a new driver every time.
    if len(sessions_to_clear) != 0:
        # Create driver so that we can clear multiple sessions at once.
        with connect_neo4j(get_settings().neo4j_url) as driver:
            for s in sessions_to_clear:
                logger.debug(f"Clearing session {s} because it expired")

                # Clear tasks.
                for task in get_session_mapping()[s].match_tasks:
                    if not task.ready():
                        task.revoke()

                # Remove mapping.
                del get_session_mapping()[s]
                # Delete from cache.
                delete_for_session(driver, s)

    # Second pass: Collect all tasks that are finished.
    for ses, match_session in get_session_mapping().items():
        for task in match_session.match_tasks:
            task_id_freed: list[str] = []

            if task.ready():
                task.forget()
                task_id_freed.append(task.id)

            if len(task_id_freed) != 0:
                logger.debug(f"Freed {len(task_id_freed)} task(s) for session {mask_string(ses)}")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Clearing neo4j cache...")
    with connect_neo4j(get_settings().neo4j_url) as driver:
        delete_all(driver)

    await free_session_tasks()

    yield


app = FastAPI(
    title="FABLE Broker",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "session",
            "description": "Create, refresh and delete match sessions.",
        },
        {
            "name": "client",
            "description": "Submit bit vectors to match sessions and fetch final or intermediate results from "
            "sessions.",
        },
    ],
    openapi_url="/openapi.json" if expose_docs else None,
    docs_url="/docs" if expose_docs else None,
    redoc_url="/redoc" if expose_docs else None,
)


@app.get("/health", summary="Check service readiness", operation_id="getHealth")
async def do_healthcheck():
    """Check whether the service is ready to process requests. Responds with a 200 on success."""
    return {"status": "ok"}


app.include_router(
    session.router,
    prefix="/session",
    tags=["session"],
)
