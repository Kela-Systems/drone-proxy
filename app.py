import os
import logging
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, HTTPException, Request

from mqtt_client import MQTTClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("drone-proxy")

mqtt: MQTTClient | None = None

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.expanduser("~"), "infra", "config.yml"),
)
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "eyesatop")
MQTT_PASS = os.environ.get("MQTT_PASS", "eyesatop")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt
    config = load_config()
    dock_serial = config["dock_serial"]

    mqtt = MQTTClient(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        drc_dock_topic=f"thing/product/{dock_serial}/drc/down",
    )
    mqtt.client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt.connect()
    yield
    mqtt.disconnect()


app = FastAPI(title="Drone Proxy", lifespan=lifespan)


def _publish(command: dict) -> dict:
    if mqtt is None or not mqtt.connected:
        raise HTTPException(status_code=503, detail="MQTT client not connected")
    ok = mqtt.publish_command(command)
    if ok:
        return {"status": "success", "command": command}
    raise HTTPException(status_code=500, detail="Failed to publish MQTT message")


@app.get("/land")
async def force_landing():
    return _publish({"method": "drc_force_landing", "data": {}, "seq": 0})


@app.post("/command")
async def custom_command(request: Request):
    body = await request.json()
    return _publish(body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
