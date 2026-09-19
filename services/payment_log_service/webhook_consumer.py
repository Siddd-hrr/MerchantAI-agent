from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import OffsetAndMetadata

logger = logging.getLogger(__name__)

WEBHOOK_TOPIC = "webhook-queue"
CONSUMER_GROUP = "payment-log-service"


class WebhookConsumer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        process_webhook: Callable[..., Awaitable[None]],
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._process_webhook = process_webhook

    async def consume_forever(self) -> None:
        consumer = AIOKafkaConsumer(
            WEBHOOK_TOPIC,
            bootstrap_servers=self._bootstrap_servers,
            group_id=CONSUMER_GROUP,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            while True:
                message = await consumer.getone()
                topic_partition = TopicPartition(message.topic, message.partition)
                try:
                    payload = json.loads(message.value.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Webhook message payload must be a JSON object.")
                    raw_body = payload.get("raw_body")
                    webhook_payload = json.loads(raw_body) if isinstance(raw_body, str) else {}
                    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
                    if not isinstance(webhook_payload, dict):
                        webhook_payload = {}
                    await self._process_webhook(
                        webhook_payload=webhook_payload,
                        received_headers=headers,
                    )
                    await consumer.commit(
                        {topic_partition: OffsetAndMetadata(message.offset + 1, "")}
                    )
                except Exception as exc:
                    logger.exception("webhook_consume_failed offset=%s error=%s", message.offset, exc)
                    consumer.seek(topic_partition, message.offset)
                    await asyncio.sleep(1.0)
        finally:
            await consumer.stop()
