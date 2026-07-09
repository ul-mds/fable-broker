import logging.config
from pathlib import Path
import os

from fable_broker.server import app
import uvicorn
import yaml


def config_server(host: str = "127.0.0.1", port: int = 8000) -> uvicorn.Server:
    os.makedirs("logs", exist_ok=True)

    with open(Path(__file__).parent.parent / "config/logging.yaml") as f:
        log_config = yaml.load(f, Loader=yaml.FullLoader)
        logging.config.dictConfig(log_config)

    config = uvicorn.Config(app, host=host, port=port, log_config=log_config)

    return uvicorn.Server(config)


def run_server():  # pragma: no cover
    config_server().run()


if __name__ == "__main__":  # pragma: no cover
    run_server()
