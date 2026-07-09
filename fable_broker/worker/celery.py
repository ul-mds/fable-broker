from celery import Celery

from fable_broker.dependencies import get_settings


celery_app = Celery("worker", broker=get_settings().amqp_url, backend=get_settings().redis_url)


if __name__ == "__main__":  # pragma: no cover
    celery_app.start()
