from __future__ import annotations

import logging
from typing import Any

from arq.connections import RedisSettings
from prometheus_client import start_http_server

from services.ingest_api.storage import S3Config, S3Storage
from services.worker.config import WorkerConfig
from services.worker.tasks import clean_file
from shared.db.session import make_engine, make_session_factory
from shared.llm import PlanGenerator
from shared.llm.generator import AnthropicPlanGenerator
from shared.observability.init import init_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_logger = logging.getLogger("worker")

_metrics_server_started = False


def _redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


def _build_storage(config: WorkerConfig, bucket: str) -> S3Storage:
    return S3Storage(
        S3Config(
            endpoint_url=config.s3_endpoint_url,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
            region=config.s3_region,
            bucket=bucket,
        )
    )


async def startup(ctx: dict[str, Any]) -> None:
    config = WorkerConfig()
    ctx["config"] = config

    init_tracing(config.service_name, config.otlp_endpoint)

    global _metrics_server_started
    if not _metrics_server_started:
        start_http_server(config.metrics_port)
        _metrics_server_started = True
        _logger.info("prometheus metrics exposed on :%d", config.metrics_port)

    engine = make_engine(config.database_url)
    ctx["engine"] = engine
    ctx["session_factory"] = make_session_factory(engine)

    bronze = _build_storage(config, config.bronze_bucket)
    silver = _build_storage(config, config.silver_bucket)
    await bronze.ensure_bucket()
    await silver.ensure_bucket()
    ctx["bronze_storage"] = bronze
    ctx["silver_storage"] = silver

    plan_generator: PlanGenerator | None = None
    if not config.disable_llm and config.anthropic_api_key:
        plan_generator = AnthropicPlanGenerator(
            model=config.anthropic_model,
            api_key=config.anthropic_api_key,
        )
        _logger.info("plan generator: Anthropic %s", config.anthropic_model)
    else:
        _logger.info("plan generator: disabled (no API key or DISABLE_LLM=1)")
    ctx["plan_generator"] = plan_generator

    _logger.info("worker startup complete: bronze=%s silver=%s", bronze.bucket, silver.bucket)


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


class WorkerSettings:
    functions = [clean_file]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 5
    redis_settings = _redis_settings(WorkerConfig().redis_url)
