"""
MQTT Client for publishing commands and subscribing to status topics.
"""
import json
import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    """MQTT client for drone and dock commands with status subscriptions"""

    def __init__(self, broker: str, port: int, **topics: str):
        self.broker = broker
        self.port = port
        self.topics = topics
        self.client = mqtt.Client()
        self.connected = False
        self._reconnecting = False

        self._subscriptions: dict[str, Optional[Callable]] = {}
        self._latest: dict[str, dict] = {}

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def connect(self):
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        logger.info("Disconnected from MQTT broker")

    # -- subscriptions --------------------------------------------------------

    def subscribe(self, topic: str, callback: Optional[Callable] = None):
        """Register a subscription. Subscribes immediately if already connected."""
        self._subscriptions[topic] = callback
        if self.connected:
            self.client.subscribe(topic)
            logger.info(f"Subscribed to {topic}")

    def get_latest(self, topic: str) -> Optional[dict]:
        return self._latest.get(topic)

    # -- callbacks ------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            self._reconnecting = False
            logger.info("Connected to MQTT broker")
            for topic in self._subscriptions:
                self.client.subscribe(topic)
                logger.info(f"Subscribed to {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker. Return code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.warning(f"Disconnected from MQTT broker. Return code: {rc}")
        if rc != 0 and not self._reconnecting:
            logger.info("Unexpected disconnect, attempting to reconnect...")
            self._reconnect()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            self._latest[msg.topic] = payload
            cb = self._subscriptions.get(msg.topic)
            if cb:
                cb(msg.topic, payload)
        except Exception as e:
            logger.error(f"Error processing message on {msg.topic}: {e}")

    # -- reconnect ------------------------------------------------------------

    def _reconnect(self):
        if self._reconnecting:
            return
        self._reconnecting = True

        def reconnect_loop():
            retry_interval = 15
            while not self.connected:
                try:
                    logger.info(f"Reconnecting to MQTT broker in {retry_interval}s...")
                    time.sleep(retry_interval)
                    self.client.reconnect()
                    logger.info("Reconnected to MQTT broker")
                    self._reconnecting = False
                    return
                except Exception as e:
                    logger.error(f"Reconnection failed: {e}")
            self._reconnecting = False

        threading.Thread(target=reconnect_loop, daemon=True).start()

    # -- publish --------------------------------------------------------------

    def publish_command(self, command: dict, target: str = "drc_dock") -> bool:
        topic = self.topics.get(target)
        if topic is None:
            logger.error(f"Unknown target '{target}'. Available: {list(self.topics)}")
            return False
        try:
            payload = json.dumps(command)
            result = self.client.publish(topic, payload)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Command published to {target} ({topic}): {command}")
                return True
            else:
                logger.error(f"Failed to publish to {target}. Return code: {result.rc}")
                return False
        except Exception as e:
            logger.error(f"Error publishing command to {target}: {e}")
            return False
