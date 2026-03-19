import os
import logging
import time
import uuid
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
dock_serial: str = ""
osd_topic: str = ""
device_state: dict = {}

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


def _on_osd(_topic: str, payload: dict):
    """Merge each OSD push into the accumulated device_state."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    for key, val in data.items():
        if isinstance(val, dict) and isinstance(device_state.get(key), dict):
            device_state[key].update(val)
        else:
            device_state[key] = val


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt, drone_name, land_url, dock_serial, osd_topic
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

    osd_topic = f"thing/product/{dock_serial}/osd"

    mqtt = MQTTClient(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        **topics,
    )
    mqtt.client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt.connect()
    mqtt.subscribe(osd_topic, callback=_on_osd)
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
    """Build a DRC command dict"""
    return {"method": method, "data": {}, "seq": 0}


def _build_services_command(method: str) -> dict:
    """Build a services command dict with gateway, tid, bid, and timestamp"""
    return {
        "tid": str(uuid.uuid4()),
        "bid": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "gateway": dock_serial,
        "method": method,
    }


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
    return _publish(_build_services_command("debug_mode_open"))


@app.get("/exit_debug_mode")
async def debug_mode_off():
    """Exit debug mode"""
    return _publish(_build_services_command("debug_mode_close"))


# ===== Drone Control =====

@app.get("/power_on_drone")
async def drone_on():
    """Power on drone"""
    return _publish(_build_services_command("drone_open"))


@app.get("/power_off_drone")
async def drone_off():
    """Power off drone"""
    return _publish(_build_services_command("drone_close"))


# ===== Dock Door Control =====

@app.get("/open_dock_door")
async def open_door():
    """Open dock cover/door"""
    return _publish(_build_services_command("cover_open"))


@app.get("/close_dock_door")
async def close_door():
    """Close dock cover/door"""
    return _publish(_build_services_command("cover_close"))


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
      background: #0f1117;
      color: #e8eaf0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      padding: 40px 16px 60px;
    }
    #drone-name {
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8b9ab5;
      margin-bottom: 6px;
    }
    #mqtt-badge {
      font-size: 0.7rem;
      font-weight: 500;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 6px;
      color: #5a6580;
    }
    #mqtt-badge .dot {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: #4a5568;
    }
    #mqtt-badge.ok        { color: #68d391; }
    #mqtt-badge.ok .dot   { background: #68d391; }
    #mqtt-badge.warn      { color: #f6e05e; }
    #mqtt-badge.warn .dot { background: #f6e05e; }
    #mqtt-badge.err       { color: #fc8181; }
    #mqtt-badge.err .dot  { background: #fc8181; }

    .land-wrap { margin-bottom: 36px; text-align: center; }
    .land-ring {
      width: 152px; height: 152px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: conic-gradient(#e53e3e calc(var(--p, 0) * 1%), #2d3348 0%);
      margin: 0 auto;
      transition: none;
    }
    .land-ring.done {
      background: #e53e3e;
    }
    #land-btn {
      width: 140px; height: 140px;
      border-radius: 50%;
      border: none;
      background: #1a1d27;
      color: #fc8181;
      font-size: 1.2rem; font-weight: 700;
      letter-spacing: 0.06em;
      cursor: pointer;
      transition: background 0.15s;
      user-select: none;
      -webkit-user-select: none;
      touch-action: none;
      position: relative;
    }
    #land-btn:hover { background: #2d1f1f; }
    .land-hint {
      margin-top: 10px;
      font-size: 0.7rem;
      color: #5a6580;
      letter-spacing: 0.04em;
      min-height: 1.2em;
    }

    .sections { width: 100%; max-width: 480px; display: flex; flex-direction: column; gap: 20px; }
    .section {
      background: #181b24;
      border: 1px solid #262a36;
      border-radius: 12px;
      padding: 16px;
    }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .section-title {
      font-size: 0.7rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #5a6580;
    }
    .badge {
      font-size: 0.65rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      gap: 5px;
      background: #1e2130;
      color: #4a5568;
      border: 1px solid #2d3348;
      transition: all 0.3s;
    }
    .badge .dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      background: #4a5568;
      transition: background 0.3s;
    }
    .badge.on        { color: #68d391; border-color: #276749; background: #13261c; }
    .badge.on .dot   { background: #68d391; }
    .badge.off       { color: #a0aec0; border-color: #2d3348; background: #1e2130; }
    .badge.off .dot  { background: #4a5568; }
    .badge.warn      { color: #f6e05e; border-color: #5a4a1e; background: #262318; }
    .badge.warn .dot { background: #f6e05e; }

    .btn-row { display: flex; gap: 10px; }
    .btn-row .action-btn { flex: 1; }
    .action-btn {
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid #2d3348;
      background: #1e2130;
      color: #c5cde0;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.12s, border-color 0.12s, transform 0.08s;
    }
    .action-btn:hover { background: #262b3f; border-color: #3d4560; }
    .action-btn:active { transform: scale(0.97); }
    .action-btn.green  { color: #68d391; border-color: #276749; }
    .action-btn.green:hover  { background: #1a2e24; border-color: #38a169; }
    .action-btn.red    { color: #fc8181; border-color: #742a2a; }
    .action-btn.red:hover    { background: #2d1f1f; border-color: #e53e3e; }
    .action-btn.blue   { color: #63b3ed; border-color: #2a4365; }
    .action-btn.blue:hover   { background: #1a2535; border-color: #3182ce; }
    .action-btn.orange { color: #f6ad55; border-color: #5a3a1e; }
    .action-btn.orange:hover { background: #2d251a; border-color: #dd6b20; }
    .action-btn.loading {
      opacity: 0.45;
      cursor: not-allowed;
      pointer-events: none;
    }

    #toast {
      position: fixed;
      bottom: 20px;
      left: 50%; transform: translateX(-50%);
      font-size: 0.85rem;
      font-weight: 500;
      padding: 8px 20px;
      border-radius: 8px;
      background: #1a2e24;
      color: #68d391;
      border: 1px solid #276749;
      opacity: 0;
      transition: opacity 0.25s;
      pointer-events: none;
      white-space: nowrap;
    }
    #toast.visible { opacity: 1; }
    #toast.error { background: #2d1f1f; color: #fc8181; border-color: #742a2a; }
  </style>
</head>
<body>
  <div id="drone-name">Loading…</div>
  <div id="mqtt-badge"><span class="dot"></span><span id="mqtt-text">Connecting…</span></div>

  <div class="land-wrap">
    <div class="land-ring" id="land-ring">
      <button id="land-btn" data-url="/land" data-label="Land command sent">LAND</button>
    </div>
    <div class="land-hint" id="land-hint">Hold to land</div>
  </div>

  <div class="sections">
    <div class="section">
      <div class="section-header">
        <div class="section-title">Flight Control</div>
      </div>
      <div class="btn-row">
        <button class="action-btn blue" data-url="/authority" data-label="Authority grabbed">Take Authority</button>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <div class="section-title">Debug Mode</div>
        <div class="badge" id="badge-debug"><span class="dot"></span><span>—</span></div>
      </div>
      <div class="btn-row">
        <button class="action-btn green" data-url="/enter_debug_mode" data-label="Debug mode entered">Enter Debug</button>
        <button class="action-btn red" data-url="/exit_debug_mode" data-label="Debug mode exited">Exit Debug</button>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <div class="section-title">Drone Power</div>
        <div class="badge" id="badge-drone"><span class="dot"></span><span>—</span></div>
      </div>
      <div class="btn-row">
        <button class="action-btn green" data-url="/power_on_drone" data-label="Drone powered on">Power On</button>
        <button class="action-btn red" data-url="/power_off_drone" data-label="Drone powered off">Power Off</button>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <div class="section-title">Dock Door</div>
        <div class="badge" id="badge-cover"><span class="dot"></span><span>—</span></div>
      </div>
      <div class="btn-row">
        <button class="action-btn green" data-url="/open_dock_door" data-label="Dock door opened">Open Door</button>
        <button class="action-btn red" data-url="/close_dock_door" data-label="Dock door closed">Close Door</button>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <div class="section-title">System</div>
      </div>
      <div class="btn-row">
        <button class="action-btn orange" data-url="/restart-dock-agent" data-method="POST" data-label="Dock agent restarted">Restart Dock Agent</button>
      </div>
    </div>
  </div>

  <div id="toast"></div>

  <script>
    const nameEl    = document.getElementById('drone-name');
    const mqttBadge = document.getElementById('mqtt-badge');
    const mqttText  = document.getElementById('mqtt-text');
    const toastEl   = document.getElementById('toast');
    let hideTimer;

    fetch('/config')
      .then(r => r.json())
      .then(d => {
        nameEl.textContent = d.drone_name;
        const landBtn = document.getElementById('land-btn');
        if (d.land_url) landBtn.dataset.url = d.land_url;
      });

    /* ---- status polling ---- */
    function setBadge(id, cls, text) {
      const el = document.getElementById(id);
      if (!el) return;
      el.className = 'badge ' + cls;
      el.querySelector('span:last-child').textContent = text;
    }

    async function pollStatus() {
      try {
        const res = await fetch('/status');
        const s = await res.json();

        if (!s.mqtt_connected) {
          mqttBadge.className = 'err';
          mqttText.textContent = 'MQTT disconnected';
          return;
        }
        if (!s.osd_received) {
          mqttBadge.className = 'warn';
          mqttText.textContent = 'MQTT ok · waiting for OSD';
          return;
        }

        mqttBadge.className = 'ok';
        mqttText.textContent = 'MQTT connected · OSD live';

        /* dock_mode_code: 0=idle, 1=local debug, 2=remote debug */
        if (s.dock_mode_code === 1 || s.dock_mode_code === 2) {
          setBadge('badge-debug', 'on', 'Active');
        } else if (s.dock_mode_code !== null && s.dock_mode_code !== undefined) {
          setBadge('badge-debug', 'off', 'Inactive');
        }

        /* drone online */
        if (s.drone_online === 1) {
          setBadge('badge-drone', 'on', 'On');
        } else if (s.drone_online !== null && s.drone_online !== undefined) {
          setBadge('badge-drone', 'off', 'Off');
        }

        /* cover_state: 0=closed, 1=open, 2=half-open */
        if (s.cover_state === 1) {
          setBadge('badge-cover', 'on', 'Open');
        } else if (s.cover_state === 2) {
          setBadge('badge-cover', 'warn', 'Half-open');
        } else if (s.cover_state === 0) {
          setBadge('badge-cover', 'off', 'Closed');
        }
      } catch (e) {
        mqttBadge.className = 'err';
        mqttText.textContent = 'Status unavailable';
      }
    }

    pollStatus();
    setInterval(pollStatus, 2000);

    /* ---- action buttons ---- */
    function showToast(msg, isError) {
      clearTimeout(hideTimer);
      toastEl.textContent = msg;
      toastEl.className = isError ? 'error visible' : 'visible';
      hideTimer = setTimeout(() => { toastEl.className = ''; }, 3000);
    }

    async function runAction(btn) {
      const url = btn.dataset.url;
      const method = btn.dataset.method || 'GET';
      const label = btn.dataset.label || 'Command sent';
      btn.classList.add('loading');
      try {
        const res = await fetch(url, { method });
        const data = await res.json();
        if (res.ok) {
          showToast(label, false);
        } else {
          showToast(data.detail || 'Error', true);
        }
      } catch (e) {
        showToast('Request failed', true);
      } finally {
        btn.classList.remove('loading');
      }
    }

    /* ---- land long-press ---- */
    const HOLD_MS = 2000;
    const landBtn  = document.getElementById('land-btn');
    const landRing = document.getElementById('land-ring');
    const landHint = document.getElementById('land-hint');
    let landStart = 0, landRaf = 0, landFired = false;

    function landProgress() {
      const elapsed = Date.now() - landStart;
      const pct = Math.min(elapsed / HOLD_MS * 100, 100);
      landRing.style.setProperty('--p', pct);
      if (pct < 100) {
        landRaf = requestAnimationFrame(landProgress);
      } else {
        landFired = true;
        landRing.classList.add('done');
        landHint.textContent = 'Sending…';
        runAction(landBtn).then(() => {
          landHint.textContent = 'Hold to land';
        });
      }
    }

    function startHold(e) {
      e.preventDefault();
      if (landFired) return;
      landStart = Date.now();
      landHint.textContent = 'Keep holding…';
      landRaf = requestAnimationFrame(landProgress);
    }

    function cancelHold() {
      cancelAnimationFrame(landRaf);
      landRing.style.setProperty('--p', 0);
      landRing.classList.remove('done');
      if (!landFired) landHint.textContent = 'Hold to land';
      landFired = false;
    }

    landBtn.addEventListener('mousedown',  startHold);
    landBtn.addEventListener('touchstart', startHold, { passive: false });
    landBtn.addEventListener('mouseup',    cancelHold);
    landBtn.addEventListener('mouseleave', cancelHold);
    landBtn.addEventListener('touchend',   cancelHold);
    landBtn.addEventListener('touchcancel', cancelHold);

    document.querySelectorAll('.action-btn').forEach(btn => {
      btn.addEventListener('click', function() { runAction(this); });
    });
  </script>
</body>
</html>""")


@app.get("/config")
async def get_config():
    return {"drone_name": drone_name, "land_url": land_url}


@app.get("/status")
async def get_status():
    """Return current device state parsed from accumulated OSD messages."""
    if mqtt is None:
        return {"mqtt_connected": False}
    if not device_state:
        return {"mqtt_connected": mqtt.connected, "osd_received": False}
    sub = device_state.get("sub_device", {})
    return {
        "mqtt_connected": mqtt.connected,
        "osd_received": True,
        "dock_mode_code": device_state.get("mode_code"),
        "cover_state": device_state.get("cover_state"),
        "drone_in_dock": device_state.get("drone_in_dock"),
        "putter_state": device_state.get("putter_state"),
        "drone_online": sub.get("device_online_status"),
        "drone_mode_code": sub.get("mode_code"),
    }


@app.get("/status/raw")
async def get_status_raw():
    """Return the full accumulated OSD state for debugging."""
    if mqtt is None:
        return {"mqtt_connected": False}
    return {"mqtt_connected": mqtt.connected, "state": device_state}


# ===== Custom Command =====

@app.post("/command")
async def custom_command(request: Request):
    """Send custom command with JSON body"""
    body = await request.json()
    return _publish(body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
