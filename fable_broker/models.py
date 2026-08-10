from fable_client import PPRLClient
from neo4j import Driver
from pydantic import BaseModel, ConfigDict

from fable_broker.config import Settings


class AppState(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    settings: Settings
    pprl_client: PPRLClient
    neo4j_driver: Driver
