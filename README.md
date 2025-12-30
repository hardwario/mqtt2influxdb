# mqtt2influxdb

[![PyPI](https://img.shields.io/pypi/v/mqtt2influxdb.svg)](https://pypi.org/project/mqtt2influxdb/)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/hardwario/mqtt2influxdb/publish.yml)](https://github.com/hardwario/mqtt2influxdb/actions)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/hardwario/mqtt2influxdb/test.yml)](https://github.com/hardwario/mqtt2influxdb/actions)
[![GitHub Release](https://img.shields.io/github/v/release/hardwario/mqtt2influxdb?sort=semver)](https://github.com/hardwario/mqtt2influxdb/releases)
[![GitHub License](https://img.shields.io/github/license/hardwario/mqtt2influxdb)](https://github.com/hardwario/mqtt2influxdb/blob/main/LICENSE)

A Python bridge between MQTT messaging and InfluxDB v3 time-series database. Subscribe to MQTT topics, process incoming messages, and write data points to InfluxDB.

---

## Features

- Subscribe to multiple MQTT topics with wildcard support (`+`, `#`)
- Write data to InfluxDB v3 with tags and fields
- Support for both JSON and raw string payloads
- JSONPath extraction from message payloads
- Mathematical expressions for computed fields
- Cron-based scheduling for conditional writes
- HTTP forwarding of processed data
- Base64 decoding support
- Daemon mode with automatic reconnection

---

## Requirements

- Python 3.10+
- InfluxDB v3 instance (Cloud or self-hosted)
- MQTT broker (Mosquitto, etc.)

---

## Installation

Using [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install mqtt2influxdb
```

Using pip:

```bash
pip install mqtt2influxdb
```

---

## Quick Start

1. Create a configuration file `config.yml`:

```yaml
mqtt:
  host: localhost
  port: 1883

influxdb:
  host: localhost
  port: 8181
  token: your-api-token
  org: your-organization
  bucket: your-bucket

points:
  - measurement: temperature
    topic: sensors/+/temperature
    fields:
      value: $.payload
    tags:
      sensor_id: $.topic[1]
```

2. Run the bridge:

```bash
mqtt2influxdb -c config.yml
```

---

## CLI Usage

```
mqtt2influxdb [OPTIONS]

Options:
  -c, --config FILE  Path to configuration file (YAML)  [required]
  -D, --debug        Enable debug logging
  -o, --output FILE  Log output file path
  -t, --test         Validate configuration without running
  -d, --daemon       Daemon mode: retry on error
  --version          Show version
  --help             Show this message and exit
```

---

## Configuration Reference

### MQTT Section

```yaml
mqtt:
  host: localhost          # Broker hostname
  port: 1883               # Broker port
  username: user           # Optional authentication
  password: pass
  cafile: /path/to/ca.crt  # Optional TLS
  certfile: /path/to/cert
  keyfile: /path/to/key
```

### InfluxDB Section

```yaml
influxdb:
  host: localhost          # InfluxDB hostname
  port: 8181               # InfluxDB port
  token: your-api-token    # API token
  org: your-organization   # Organization name
  bucket: your-bucket      # Default bucket
  enable_gzip: false       # Optional gzip compression
```

### Points Section

```yaml
points:
  - measurement: temperature
    topic: node/+/thermometer/+/temperature
    bucket: custom_bucket   # Optional: override default bucket
    schedule: '0 * * * *'   # Optional: cron filter
    fields:
      value: $.payload
      converted:
        value: $.payload.raw
        type: float
      calculated: = 32 + ($.payload.celsius * 9 / 5)
    tags:
      id: $.topic[1]
      channel: $.topic[3]
```

### Type Conversion

Fields support optional type conversion:

```yaml
fields:
  temperature:
    value: $.payload.temp
    type: float
```

| Type | Description | Example |
|------|-------------|---------|
| `float` | Floating-point number | `"123"` → `123.0` |
| `int` | Integer number | `"42"` → `42` |
| `str` | String | `123` → `"123"` |
| `bool` | Boolean | `1` → `true` |
| `booltoint` | Boolean converted to 0/1 | `true` → `1` |

### Payload Formats

Both JSON and raw string payloads are supported:

| Payload | Parsed As | `$.payload` Value |
|---------|-----------|-------------------|
| `25.5` | JSON number | `25.5` (float) |
| `{"temp": 25}` | JSON object | `{"temp": 25}` |
| `[1, 2, 3]` | JSON array | `[1, 2, 3]` |
| `"hello"` | JSON string | `"hello"` |
| `ON` | Raw string | `"ON"` |
| `Device ready` | Raw string | `"Device ready"` |

Raw strings are useful for simple MQTT messages like Tasmota power states (`ON`/`OFF`) or status messages.

### JSONPath Syntax

- `$.payload` - Entire payload (JSON or raw string)
- `$.payload.temperature` - Nested field (JSON only)
- `$.payload.data[0]` - Array index (JSON only)
- `$.topic[n]` - Topic segment (0-indexed)
- `$.payload['pm2.5']` - Field with special characters (dot, space, etc.)

**Special Characters:** Use bracket notation with quotes for field names containing dots, spaces, or other reserved characters:

```yaml
# For payload: {"air_quality_sensor": {"pm2.5": 5}}
fields:
  pm25: $.payload.air_quality_sensor['pm2.5']
```

### Environment Variables

Use `${VAR}` or `${VAR:default}` syntax to substitute environment variables in any string value.

```yaml
mqtt:
  host: ${MQTT2INFLUXDB_MQTT_HOST:localhost}
  port: ${MQTT2INFLUXDB_MQTT_PORT:1883}
  username: ${MQTT2INFLUXDB_MQTT_USERNAME:}
  password: ${MQTT2INFLUXDB_MQTT_PASSWORD:}

influxdb:
  host: ${MQTT2INFLUXDB_INFLUXDB_HOST:localhost}
  port: ${MQTT2INFLUXDB_INFLUXDB_PORT:8181}
  token: ${MQTT2INFLUXDB_INFLUXDB_TOKEN}
  org: ${MQTT2INFLUXDB_INFLUXDB_ORG:default}
  bucket: ${MQTT2INFLUXDB_INFLUXDB_BUCKET:metrics}
```

- `${VAR}` - Required variable (error if not set)
- `${VAR:default}` - Optional variable with default value
- `${VAR:}` - Optional variable with empty default

### Optional HTTP Forwarding

```yaml
http:
  destination: https://example.com/api
  action: post
  username: user
  password: pass
```

### Optional Base64 Decoding

```yaml
base64decode:
  source: $.payload.data
  target: data
```

---

## Development

```bash
git clone https://github.com/hardwario/mqtt2influxdb.git
cd mqtt2influxdb
uv sync
uv run mqtt2influxdb -c config-tower.yml --debug
```

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

Made with ❤ by [**HARDWARIO a.s.**](https://www.hardwario.com/) in the heart of Europe.
