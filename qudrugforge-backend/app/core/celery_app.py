from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "qudrugforge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.pipeline", "app.tasks.imports"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.pipeline.*": {"queue": "pipeline"},
        "app.tasks.imports.*": {"queue": "imports"},
    },
    task_default_queue="default",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.ENABLE_DEV_JOB_SIMULATION,
)

import asyncio
from celery.signals import worker_process_init, worker_process_shutdown
from app.core.database import connect_to_mongo, close_mongo_connection

@worker_process_init.connect
def init_celery_worker(**kwargs):
    asyncio.run(connect_to_mongo())

@worker_process_shutdown.connect
def shutdown_celery_worker(**kwargs):
    asyncio.run(close_mongo_connection())
