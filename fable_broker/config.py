from pydantic import AnyUrl, AnyHttpUrl, AmqpDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# https://neo4j.com/docs/upgrade-migration-guide/current/migration/drivers/new-uri-schemes/
class Neo4jDsn(AnyUrl):
    allowed_schemes = {"neo4j", "neo4j+s", "neo4j+ssc", "bolt", "bolt+s", "bolt+ssc"}


class Settings(BaseSettings):
    pprl_service_base_url: str = "http://localhost:8080"
    neo4j_url: str = "bolt://localhost:7687"
    amqp_url: str = "amqp://guest:guest@localhost:5672//"
    redis_url: str = "redis://localhost:6379/0"

    # Treated as seconds.
    max_session_timeout: int = 3600
    refresh_session_interval: int = 3600
    task_cleanup_interval: int = 10

    expose_docs: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        frozen=True,
    )

    @field_validator("pprl_service_base_url")
    @classmethod
    def validate_pprl_service_base_url(cls, v):
        AnyHttpUrl(v)
        return v

    @field_validator("neo4j_url")
    @classmethod
    def validate_neo4j_url(cls, v):
        Neo4jDsn(v)
        return v

    @field_validator("amqp_url")
    @classmethod
    def validate_amqp_url(cls, v):
        AmqpDsn(v)
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v):
        RedisDsn(v)
        return v
