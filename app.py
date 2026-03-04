import os
import logging
import subprocess
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

    drone_serial = config.get("drone_serial")

    topics = {
        "drc_dock": f"thing/product/{dock_serial}/drc/down",
        "dock_services": f"thing/product/{dock_serial}/services",
    }

    mqtt = MQTTClient(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        **topics,
    )
    mqtt.client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt.connect()
    yield
    mqtt.disconnect()


app = FastAPI(title="Drone Proxy", lifespan=lifespan)


def _publish(command: dict, target: str = "dock_services") -> dict:
    if mqtt is None or not mqtt.connected:
        raise HTTPException(status_code=503, detail="MQTT client not connected")
    ok = mqtt.publish_command(command, target=target)
    if ok:
        return {"status": "success", "target": target, "command": command}
    raise HTTPException(status_code=500, detail="Failed to publish MQTT message")


def _build_command(method: str) -> dict:
    """Build a command dict with method, empty data, and seq 0"""
    return {"method": method, "data": {}, "seq": 0}


# ===== DRC Commands =====

@app.get("/land")
async def force_landing():
    """Force drone to land"""
    return _publish(_build_command("drc_force_landing"), target="drc_dock")


@app.get("/authority")
async def take_authority():
    """Take control authority"""
    return _publish(_build_command("drc_authority_grab"), target="drc_dock")


# ===== Debug Mode =====

@app.get("/enter_debug_mode")
async def debug_mode_on():
    """Enter debug mode"""
    return _publish(_build_command("debug_mode_open"))


@app.get("/exit_debug_mode")
async def debug_mode_off():
    """Exit debug mode"""
    return _publish(_build_command("debug_mode_close"))


# ===== Drone Control =====

@app.get("/power_on_drone")
async def drone_on():
    """Power on drone"""
    return _publish(_build_command("drone_open"))


@app.get("/power_off_drone")
async def drone_off():
    """Power off drone"""
    return _publish(_build_command("drone_close"))


# ===== Dock Door Control =====

@app.get("/open_dock_door")
async def open_door():
    """Open dock cover/door"""
    return _publish(_build_command("cover_open"))


@app.get("/close_dock_door")
async def close_door():
    """Close dock cover/door"""
    return _publish(_build_command("cover_close"))


# ===== System Control =====

@app.post("/restart_dock_agent")
async def restart_dock_agent():
    """Restart the dock-agent Docker container"""
    try:
        result = subprocess.run(
            ["docker", "restart", "dock-agent"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return {
                "status": "success", 
                "detail": "dock-agent container restarted successfully"
            }
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to restart dock-agent: {result.stderr}"
            )
            
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500, 
            detail="Timeout while restarting dock-agent container"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error restarting dock-agent: {str(e)}"
        )


# ===== Custom Command =====

@app.post("/command")
async def custom_command(request: Request):
    """Send custom command with JSON body"""
    body = await request.json()
    return _publish(body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
