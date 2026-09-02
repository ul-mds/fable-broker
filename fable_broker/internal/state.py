from dataclasses import dataclass, field

from celery.result import AsyncResult
from fable_model.match import MatchConfig
from pydantic import SecretStr


@dataclass
class MatchSession:
    config: MatchConfig
    token: SecretStr
    expires_at: int
    clients: set[SecretStr] = field(default_factory=set)
    match_tasks: list[AsyncResult] = field(default_factory=list)
