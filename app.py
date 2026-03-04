import os
import logging
from contextlib import asynccontextmanager

import docker
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from mqtt_client import MQTTClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("drone-proxy")

mqtt: MQTTClient | None = None
drone_name: str = "Drone"
land_url: str = "/land"

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.expanduser("~"), "infra", "config.yml"),
)
APP_CONFIG_PATH = os.environ.get(
    "APP_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "app_config.yml"),
)
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "eyesatop")
MQTT_PASS = os.environ.get("MQTT_PASS", "eyesatop")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_app_config() -> dict:
    try:
        with open(APP_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.warning(f"app_config.yml not found at {APP_CONFIG_PATH}, using defaults")
        return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt, drone_name, land_url
    app_config = load_app_config()
    drone_name = app_config.get("drone_name", "Drone")
    land_url = app_config.get("land_url", "/land")

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

@app.post("/restart-dock-agent")
async def restart_dock_agent():
    """Restart the dock-agent Docker container"""
    try:
        client = docker.from_env()
        container = client.containers.get("dock-agent")
        container.restart(timeout=30)
        return {"status": "success", "detail": "dock-agent container restarted successfully"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="dock-agent container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error restarting dock-agent: {str(e)}")


# ===== UI =====

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Drone Proxy</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: #0f1117;
      color: #e8eaf0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      gap: 32px;
    }
    #drone-name {
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8b9ab5;
    }
    #land-btn {
      width: 160px;
      height: 160px;
      border-radius: 50%;
      border: 3px solid #e53e3e;
      background: #1a1d27;
      color: #fc8181;
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      cursor: pointer;
      transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
      box-shadow: 0 0 0 0 rgba(229,62,62,0);
    }
    #land-btn:hover {
      background: #2d1f1f;
      box-shadow: 0 0 24px 4px rgba(229,62,62,0.35);
    }
    #land-btn:active { transform: scale(0.95); }
    #land-btn.loading {
      opacity: 0.5;
      cursor: not-allowed;
      pointer-events: none;
    }
    #status {
      font-size: 0.875rem;
      min-height: 1.2em;
      color: #68d391;
    }
    #status.error { color: #fc8181; }
  </style>
</head>
<body>
  <div id="drone-name">Loading…</div>
  <button id="land-btn">LAND</button>
  <div id="status"></div>

  <script>
    const nameEl = document.getElementById('drone-name');
    const btn = document.getElementById('land-btn');
    const status = document.getElementById('status');

    let landUrl = '/land';
    fetch('/config')
      .then(r => r.json())
      .then(d => {
        nameEl.textContent = d.drone_name;
        landUrl = d.land_url || '/land';
      });

    btn.addEventListener('click', async () => {
      btn.classList.add('loading');
      status.textContent = '';
      status.className = '';
      try {
        const res = await fetch(landUrl);
        const data = await res.json();
        if (res.ok) {
          status.textContent = 'Land command sent';
        } else {
          status.className = 'error';
          status.textContent = data.detail || 'Error';
        }
      } catch (e) {
        status.className = 'error';
        status.textContent = 'Request failed';
      } finally {
        btn.classList.remove('loading');
      }
    });
  </script>
</body>
</html>""")


@app.get("/config")
async def get_config():
    return {"drone_name": drone_name, "land_url": land_url}


# ===== Custom Command =====

@app.post("/command")
async def custom_command(request: Request):
    """Send custom command with JSON body"""
    body = await request.json()
    return _publish(body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
