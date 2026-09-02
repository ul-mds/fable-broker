import secrets
from typing import Annotated

from fable_client import PPRLClient
from fastapi import Depends, Request
from neo4j import Driver
from pydantic import SecretStr

from fable_broker.config import Settings
from fable_broker.internal.state import MatchSession
from fable_broker.models import AppState


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state


def get_settings(state: Annotated[AppState, Depends(get_app_state)]) -> Settings:
    return state.settings


_session_mapping: dict[SecretStr, MatchSession] = {}


def get_session_mapping() -> dict[SecretStr, MatchSession]:
    return _session_mapping


def get_neo4j_driver(state: Annotated[AppState, Depends(get_app_state)]) -> Driver:
    return state.neo4j_driver


def next_secret() -> SecretStr:
    return SecretStr(secrets.token_hex(16))


def get_pprl_client(state: Annotated[AppState, Depends(get_app_state)]) -> PPRLClient:
    return state.pprl_client
