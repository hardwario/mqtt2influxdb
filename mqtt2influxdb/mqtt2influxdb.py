"""MQTT to InfluxDB v3 bridge."""

import base64
import json
import logging
import signal
import sys
from datetime import datetime, timezone

import jsonpath_ng
import paho.mqtt.client as mqtt
import pycron
import requests
from influxdb_client_3 import InfluxDBClient3, Point
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from .config import Config, FieldConfig
from .expr import variable_to_jsonpath

# Constants
HTTP_TIMEOUT = 10  # seconds
MAX_BASE64_SIZE = 1024 * 1024  # 1MB limit for base64 decoded data


class Mqtt2InfluxDB:
    """Bridge between MQTT and InfluxDB v3."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._points = config.points
        self._running = False

        # Initialize InfluxDB v3 client
        influxdb_host = f"{config.influxdb.host}:{config.influxdb.port}"
        self._influxdb = InfluxDBClient3(
            host=influxdb_host,
            token=config.influxdb.token,
            org=config.influxdb.org,
            database=config.influxdb.bucket,
            enable_gzip=config.influxdb.enable_gzip,
        )

        # Initialize MQTT client (paho-mqtt v2 API)
        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if config.mqtt.username:
            self._mqtt.username_pw_set(
                config.mqtt.username,
                config.mqtt.password,
            )

        if config.mqtt.cafile:
            self._mqtt.tls_set(
                ca_certs=str(config.mqtt.cafile),
                certfile=str(config.mqtt.certfile) if config.mqtt.certfile else None,
                keyfile=str(config.mqtt.keyfile) if config.mqtt.keyfile else None,
            )

        self._mqtt.on_connect = self._on_mqtt_connect
        self._mqtt.on_disconnect = self._on_mqtt_disconnect
        self._mqtt.on_message = self._on_mqtt_message

    def run(self) -> None:
        """Start the MQTT to InfluxDB bridge."""
        self._running = True

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logging.info(
            "Connecting to MQTT broker %s:%d (TLS: %s)",
            self._config.mqtt.host,
            self._config.mqtt.port,
            bool(self._config.mqtt.cafile),
        )

        self._mqtt.connect(
            self._config.mqtt.host,
            self._config.mqtt.port,
            keepalive=60,
        )
        self._mqtt.loop_forever()

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logging.info("Received %s signal, shutting down...", sig_name)
        self.stop()

    def stop(self) -> None:
        """Stop the bridge and clean up resources."""
        if not self._running:
            return
        self._running = False
        logging.info("Stopping MQTT client...")
        self._mqtt.disconnect()
        self._mqtt.loop_stop()
        logging.info("Closing InfluxDB client...")
        self._influxdb.close()
        logging.info("Shutdown complete")

    def _on_mqtt_connect(
        self, client, userdata, flags, reason_code, properties
    ) -> None:
        """Handle MQTT connection."""
        logging.info("Connected to MQTT broker (reason: %s)", reason_code)

        if reason_code.is_failure:
            logging.error("Connection failed: %s", reason_code)
            return

        for point in self._points:
            qos = point.qos
            logging.info("Subscribing to: %s (QoS: %d)", point.topic, qos)
            client.subscribe(point.topic, qos=qos)

    def _on_mqtt_disconnect(
        self, client, userdata, flags, reason_code, properties
    ) -> None:
        """Handle MQTT disconnection."""
        logging.info("Disconnected from MQTT broker (reason: %s)", reason_code)

    def _on_mqtt_message(self, client, userdata, message) -> None:
        """Process incoming MQTT message."""
        # Log topic and payload size (not content) to avoid exposing sensitive data
        logging.debug(
            "Message received: topic=%s, payload_size=%d bytes",
            message.topic,
            len(message.payload),
        )

        msg = None

        for point_config in self._points:
            if not mqtt.topic_matches_sub(point_config.topic, message.topic):
                continue

            # Parse message once
            if msg is None:
                msg = self._parse_message(message)
                if msg is None:
                    return

            # Check schedule
            if point_config.schedule and not pycron.is_now(point_config.schedule):
                logging.debug(
                    "Skipping %s due to schedule %s",
                    message.topic,
                    point_config.schedule,
                )
                continue

            # Process and write point
            self._process_point(point_config, msg)

    def _parse_message(self, message) -> dict | None:
        """Parse MQTT message into structured format.

        Supports JSON, raw string, and binary payloads. If JSON parsing fails,
        the raw string is used. For binary payloads (non-UTF-8), hex encoding
        is provided.
        """
        payload = None
        payload_binary = None

        # Try to decode as UTF-8 first
        try:
            payload_str = message.payload.decode("utf-8")
            # Try to parse as JSON, fall back to raw string
            if payload_str == "":
                payload = None
            else:
                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    # Keep payload as raw string if not valid JSON
                    logging.debug(
                        "Payload is not JSON, using raw string: topic=%s",
                        message.topic,
                    )
                    payload = payload_str
        except UnicodeDecodeError:
            # Binary payload - provide hex encoding
            logging.debug(
                "Binary payload detected (non-UTF-8): topic=%s, size=%d bytes",
                message.topic,
                len(message.payload),
            )
            payload_binary = {
                "raw": message.payload,
                "hex": message.payload.hex(),
                "size": len(message.payload),
            }

        msg = {
            "topic": message.topic.split("/"),
            "payload": payload,
            "payload_binary": payload_binary,
            "timestamp": getattr(message, "timestamp", None),
            "qos": message.qos,
        }

        # Handle base64 decoding if configured
        if self._config.base64decode:
            try:
                source_path = jsonpath_ng.parse(self._config.base64decode.source)
                matches = source_path.find(msg)
                if matches:
                    data = matches[0].value
                    # Check size limit before decoding
                    if len(data) > MAX_BASE64_SIZE:
                        logging.warning(
                            "Base64 data exceeds size limit (%d bytes > %d bytes)",
                            len(data),
                            MAX_BASE64_SIZE,
                        )
                    else:
                        decoded = base64.b64decode(data)
                        # Also check decoded size
                        if len(decoded) > MAX_BASE64_SIZE:
                            logging.warning(
                                "Decoded base64 data exceeds size limit (%d bytes)",
                                len(decoded),
                            )
                        else:
                            target = self._config.base64decode.target
                            msg["base64decoded"] = {
                                target: {
                                    "raw": decoded,
                                    "hex": decoded.hex(),
                                }
                            }
            except base64.binascii.Error as e:
                logging.warning("Base64 decode failed (invalid data): %s", e)
            except Exception as e:
                logging.warning("Base64 decode failed: %s", e)

        return msg

    def _process_point(self, point_config, msg: dict) -> None:
        """Process a single point configuration and write to InfluxDB."""
        # Get measurement name
        measurement = self._get_value(point_config.measurement, msg)
        if measurement is None:
            logging.warning("Could not determine measurement name")
            return

        # Build InfluxDB Point
        point = Point(measurement)

        # Add timestamp
        timestamp = self._get_timestamp(msg)
        point.time(timestamp)

        # Add tags
        for tag_name, tag_value_spec in point_config.tags.items():
            value = self._get_value(tag_value_spec, msg)
            if value is not None:
                point.tag(tag_name, str(value))

        # Add fields
        fields_added = 0
        for field_name, field_spec in point_config.fields.items():
            if isinstance(field_spec, FieldConfig):
                value = self._get_value(field_spec.value, msg)
                field_type = field_spec.type
            else:
                value = self._get_value(field_spec, msg)
                field_type = None

            if value is None:
                logging.warning("Could not get value for field: %s", field_name)
                continue

            # Type conversion
            if field_type:
                value = self._convert_type(value, field_type)

            if value is not None:
                point.field(field_name, value)
                fields_added += 1

        if fields_added == 0:
            logging.warning("No fields to write for measurement: %s", measurement)
            return

        # Write to InfluxDB
        try:
            bucket = point_config.bucket or self._config.influxdb.bucket
            self._influxdb.write(point, database=bucket)
            logging.debug("Wrote point to InfluxDB: %s", measurement)
        except ConnectionError as e:
            logging.error(
                "Failed to write to InfluxDB (connection error): %s", e
            )
        except TimeoutError as e:
            logging.error("Failed to write to InfluxDB (timeout): %s", e)
        except Exception as e:
            logging.error(
                "Failed to write to InfluxDB: %s: %s",
                type(e).__name__,
                e,
            )

        # HTTP forwarding
        if self._config.http and point_config.httpcontent:
            self._forward_http(point_config, msg)

    def _get_value(self, spec: str, msg: dict):
        """Extract value from message using spec (literal, JSONPath, or expression)."""
        if not spec:
            return None

        # Check for expression (starts with =)
        if isinstance(spec, str) and spec.startswith("="):
            from .expr import parse_expression

            try:
                expr = parse_expression(spec)
                variables = {}
                for var in expr.variables():
                    if var.startswith("JSON__"):
                        json_path = variable_to_jsonpath(var)
                        path = jsonpath_ng.parse(json_path)
                        matches = path.find(msg)
                        if matches:
                            variables[var] = matches[0].value
                        else:
                            logging.error("Unable to find JSON field: %s", json_path)
                logging.debug(
                    "Evaluating expression %s with variables %s",
                    expr.toString(),
                    variables,
                )
                return expr.evaluate(variables)
            except Exception as e:
                logging.error("Expression evaluation failed: %s", e)
                return None

        # Check for JSONPath
        if isinstance(spec, str) and "$." in spec:
            try:
                path = jsonpath_ng.parse(spec)
                matches = path.find(msg)
                if matches:
                    return matches[0].value
            except Exception as e:
                logging.error("JSONPath evaluation failed: %s", e)
            return None

        # Literal string
        return spec

    def _get_timestamp(self, msg: dict) -> datetime:
        """Get timestamp from message payload or current time.

        Looks for a 'timestamp' field in the payload (Unix timestamp).
        Falls back to current time if not found or invalid.
        """
        payload = msg.get("payload", {})
        if isinstance(payload, dict) and "timestamp" in payload:
            try:
                return datetime.fromtimestamp(
                    payload["timestamp"],
                    tz=timezone.utc,
                )
            except (TypeError, ValueError, OSError) as e:
                logging.debug(
                    "Invalid timestamp in payload (%s), using current time",
                    e,
                )
        else:
            logging.debug("No timestamp in payload, using current time")
        return datetime.now(tz=timezone.utc)

    def _convert_type(self, value, type_name: str):
        """Convert value to specified type."""
        try:
            if type_name == "float":
                return float(value)
            elif type_name == "int":
                return int(value)
            elif type_name == "str":
                return str(value)
            elif type_name == "bool":
                return bool(value)
            elif type_name == "booltoint":
                return int(bool(value))
        except (ValueError, TypeError) as e:
            logging.warning(
                "Type conversion failed for %s to %s: %s", value, type_name, e
            )
        return None

    def _forward_http(self, point_config, msg: dict) -> None:
        """Forward data to HTTP endpoint."""
        http_data = {}
        for key, spec in point_config.httpcontent.items():
            value = self._get_value(spec, msg)
            if value is not None:
                http_data[key] = value

        if not http_data:
            return

        http_config = self._config.http
        # Method is validated at config time, so this should always succeed
        method = getattr(requests, http_config.action.lower())

        auth = None
        if http_config.username:
            auth = HTTPBasicAuth(http_config.username, http_config.password)

        try:
            response = method(
                url=http_config.destination,
                data=http_data,
                auth=auth,
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            logging.debug(
                "HTTP forward to %s (status: %d)",
                http_config.destination,
                response.status_code,
            )
        except requests.Timeout:
            logging.error(
                "HTTP forward timeout after %ds: %s",
                HTTP_TIMEOUT,
                http_config.destination,
            )
        except requests.ConnectionError as e:
            logging.error(
                "HTTP forward connection error: %s: %s",
                http_config.destination,
                e,
            )
        except requests.HTTPError as e:
            logging.error(
                "HTTP forward failed (status %d): %s",
                e.response.status_code if e.response else 0,
                http_config.destination,
            )
        except RequestException as e:
            logging.error("HTTP forward failed: %s: %s", type(e).__name__, e)
