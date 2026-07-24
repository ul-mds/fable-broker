import secrets
from functools import lru_cache
from typing import AsyncGenerator, Annotated

from fable_client import PPRLClient
from fastapi import Depends
from neo4j import Driver

from fable_broker.config import Settings
from fable_broker.internal.graph import connect_neo4j
from fable_broker.internal.state import MatchSession


@lru_cache()
def get_settings():
    return Settings()


_session_mapping: dict[str, MatchSession] = {}


def get_session_mapping() -> dict[str, MatchSession]:
    return _session_mapping


async def get_neo4j_driver(settings=Depends(get_settings)) -> AsyncGenerator[Driver, None]:
    driver = connect_neo4j(settings.neo4j_url)
    try:
        yield driver
    finally:
        driver.close()


def next_secret():
    return secrets.token_hex(16)


def get_pprl_client(settings: Annotated[Settings, Depends(get_settings)]) -> PPRLClient:
    return PPRLClient(base_url=str(settings.pprl_service_base_url))
