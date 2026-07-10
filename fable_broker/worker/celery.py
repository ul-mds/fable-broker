import os

from celery import Celery

from fable_broker.dependencies import get_settings


celery_app = Celery("worker", broker=get_settings().amqp_url, backend=get_settings().redis_url)

celery_app.autodiscover_tasks(["fable_broker.worker"])


def start_worker():  # pragma: no cover
    os.makedirs("logs", exist_ok=True)

    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--logfile=logs/celery.log",
        ]
    )
