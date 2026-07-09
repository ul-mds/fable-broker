from dataclasses import dataclass, field

from celery.result import AsyncResult
from fable_model.match import MatchConfig


@dataclass
class MatchSession:
    config: MatchConfig
    token: str
    expires_at: int
    clients: set[str] = field(default_factory=set)
    match_tasks: list[AsyncResult] = field(default_factory=list)
