# Drone Proxy

A FastAPI web application that provides a proxy interface for sending commands to drone dock devices via MQTT. Includes a web dashboard for one-click control.

## Features

- **Web dashboard** at `/` with real-time status badges, hold-to-land button, and action controls
- **REST API** for drone commands: landing, authority, debug mode, power, dock door, and more
- **Real-time OSD status** via MQTT subscription with polling endpoint
- **Docker container management** — restart the `dock-agent` container remotely
- **Custom commands** via `POST /command`
- **Dockerized** with Docker Compose for easy deployment

## Prerequisites

- Docker and Docker Compose
- Access to an MQTT broker (default `localhost:1883`)
- `~/infra/config.yml` with your `dock_serial`
- `~/infra/data/identity.txt` (optional) with drone name metadata

## Quick Start

```bash
git clone <repo-url> drone-proxy
cd drone-proxy
```

Create the configuration file before installing:

```bash
mkdir -p ~/infra/data
cat > ~/infra/config.yml <<EOF
dock_serial: your_dock_serial_here
EOF
```

Then build and start:

```bash
./install.sh
```

The install script will build the Docker image (with host networking) and start the container. The dashboard will be available at `http://localhost:3001`.

## Configuration

### config.yml

The application reads `~/infra/config.yml` (mounted into the container at `/config/config.yml`):

```yaml
dock_serial: your_dock_serial_here
```

The `dock_serial` is used to construct MQTT topics for your specific device.

### identity.txt (optional)

Place a JSON file at `~/infra/data/identity.txt` to set the drone name shown in the dashboard:

```json
{"name": "My Drone"}
```

If missing, the name defaults to "Drone".

### Environment Variables

These are configured in `docker-compose.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_PATH` | Path to config.yml inside the container | `/config/config.yml` |
| `IDENTITY_PATH` | Path to identity.txt inside the container | `/config/identity.txt` |
| `MQTT_BROKER` | MQTT broker hostname | `localhost` |
| `MQTT_PORT` | MQTT broker port | `1883` |
| `MQTT_USER` | MQTT username | `eyesatop` |
| `MQTT_PASS` | MQTT password | `eyesatop` |

## API Endpoints

### DRC Commands

| Method | Path | Description |
|--------|------|-------------|
| GET | `/land` | Force-land the drone (DRC `drc_force_landing`) |
| GET | `/authority` | Grab control authority (DRC `drc_authority_grab`) |

### Dock Services Commands

| Method | Path | Description |
|--------|------|-------------|
| GET | `/enter_debug_mode` | Enter debug mode (`debug_mode_open`) |
| GET | `/exit_debug_mode` | Exit debug mode (`debug_mode_close`) |
| GET | `/power_on_drone` | Power on the drone (`drone_open`) |
| GET | `/power_off_drone` | Power off the drone (`drone_close`) |
| GET | `/open_dock_door` | Open dock cover (`cover_open`) |
| GET | `/close_dock_door` | Close dock cover (`cover_close`) |

### Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Parsed device status (MQTT connection, OSD data, mode, cover state, etc.) |
| GET | `/status/raw` | Full accumulated OSD state for debugging |

### System

| Method | Path | Description |
|--------|------|-------------|
| POST | `/restart-dock-agent` | Restart the `dock-agent` Docker container |
| POST | `/command` | Send an arbitrary command JSON body via MQTT |

### Dashboard

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web dashboard with real-time controls and status |

## Container Management

```bash
docker compose up -d          # start
docker compose down            # stop
docker compose up -d --build   # rebuild and start
docker compose logs -f         # view logs
```

## How It Works

1. The FastAPI application starts inside a Docker container on port 3001
2. On startup it reads the `dock_serial` from the mounted `config.yml` and the drone name from `identity.txt`
3. Connects to the MQTT broker, subscribes to the OSD topic (`thing/product/{dock_serial}/osd`), and keeps the connection alive with automatic reconnection
4. OSD messages are accumulated into an in-memory state that powers the `/status` endpoint and the dashboard badges
5. API calls publish commands to `thing/product/{dock_serial}/drc/down` (DRC) or `thing/product/{dock_serial}/services` (dock services)
6. The Docker socket is mounted so the app can restart the `dock-agent` container on demand
