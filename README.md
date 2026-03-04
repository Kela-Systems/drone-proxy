# Drone Proxy

A FastAPI web application that provides a proxy interface for sending commands to drone devices via MQTT.

## Features

- **Simple REST API** for sending commands to drone devices
- **Force landing endpoint** (`/land`) that publishes MQTT messages to trigger drone landing
- **Dockerized** with Docker Compose for easy deployment
- **Error handling** with proper HTTP status codes and error messages

## Prerequisites

- Docker and Docker Compose
- Access to MQTT broker (localhost:1883)
- `config.yml` file with dock_serial configuration in `~/infra/` directory

## Quick Start

```bash
git clone <repo-url> drone-proxy
cd drone-proxy
./install.sh
```

The install script will:
1. Create `~/infra/` directory if it doesn't exist
2. Create `~/infra/config.yml` from the example template (if it doesn't exist)
3. Build the Docker image and start the container

Then edit `~/infra/config.yml` with your dock_serial and restart:

```bash
docker compose up -d
```

The API will be available at `http://localhost:3001`.

## Configuration

The application reads configuration from `~/infra/config.yml`. Create this file with your dock serial number:

```yaml
dock_serial: your_dock_serial_here
```

This is used to construct the MQTT topic for sending commands to your specific device.

### Environment Variables

These are configured in `docker-compose.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_PATH` | Path to config.yml inside the container | `/config/config.yml` |
| `MQTT_BROKER` | MQTT broker hostname | `localhost` |
| `MQTT_PORT` | MQTT broker port | `1883` |
| `MQTT_USER` | MQTT username | `eyesatop` |
| `MQTT_PASS` | MQTT password | `eyesatop` |

## API Endpoints

### GET /land

Sends a force landing command to the drone.

**Response:**
- `200 OK`: Command sent successfully
- `500 Internal Server Error`: Failed to send command

**Example:**
```bash
curl http://localhost:3001/land
```

**Success Response:**
```json
{
  "status": "success",
  "detail": "Force landing command published"
}
```

## Container Management

```bash
docker compose up -d          # start
docker compose down            # stop
docker compose up -d --build   # rebuild and start
docker compose logs -f         # view logs
```

## How It Works

1. The FastAPI application starts inside a Docker container on port 8000
2. On startup, it reads the dock_serial from the mounted `config.yml`
3. Connects to the MQTT broker and keeps the connection alive
4. When `/land` endpoint is called, publishes a force landing command to `thing/product/{dock_serial}/drc/down`
5. Returns success/error response based on the publish result
