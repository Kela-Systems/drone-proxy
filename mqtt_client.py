"""
MQTT Client for publishing commands via drone proxy
"""
import json
import logging
import threading
import time
import paho.mqtt.client as mqtt
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class MQTTClient:
    """MQTT client for dock commands"""
    
    def __init__(self, broker: str, port: int, drc_dock_topic: str):
        self.broker = broker
        self.port = port
        self.drc_dock_topic = drc_dock_topic
        self.client = mqtt.Client()
        self.connected = False
        self._reconnecting = False
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
    def connect(self):
        """Connect to MQTT broker"""
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            
    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        logger.info("Disconnected from MQTT broker")
        
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.connected = True
            self._reconnecting = False
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker. Return code: {rc}")
            
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self.connected = False
        logger.warning(f"Disconnected from MQTT broker. Return code: {rc}")

        if rc != 0 and not self._reconnecting:
            logger.info("Unexpected disconnect, attempting to reconnect...")
            self._reconnect()

    def _reconnect(self):
        """Attempt to reconnect to MQTT broker"""
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

        thread = threading.Thread(target=reconnect_loop, daemon=True)
        thread.start()

    def publish_command(self, command: dict) -> bool:
        """Publish a command to the drc_dock topic"""
        try:
            payload = json.dumps(command)
            result = self.client.publish(self.drc_dock_topic, payload)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Command published to {self.drc_dock_topic}: {command}")
                return True
            else:
                logger.error(f"Failed to publish command. Return code: {result.rc}")
                return False
        except Exception as e:
            logger.error(f"Error publishing command: {e}")
            return False
