"""Integration tests for MQTT to InfluxDB flow.

These tests verify the complete message processing pipeline using mocked
external services (MQTT broker and InfluxDB).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from mqtt2influxdb.config import Config
from mqtt2influxdb.mqtt2influxdb import Mqtt2InfluxDB


@pytest.fixture
def mock_services():
    """Mock both MQTT and InfluxDB services."""
    with patch("mqtt2influxdb.mqtt2influxdb.InfluxDBClient3") as mock_influx:
        with patch("mqtt2influxdb.mqtt2influxdb.mqtt.Client") as mock_mqtt:
            yield {"influxdb": mock_influx, "mqtt": mock_mqtt}


class TestBasicFlow:
    """Tests for basic MQTT to InfluxDB flow."""

    def test_simple_numeric_payload(self, mock_services):
        """Test processing simple numeric payload."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "temperature",
                        "topic": "test/+/temperature",
                        "fields": {"value": "$.payload"},
                        "tags": {"sensor_id": "$.topic[1]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        # Simulate MQTT message
        message = MagicMock()
        message.topic = "test/sensor1/temperature"
        message.payload = b"25.5"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        # Verify write was called
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        point = call_args[0][0]

        # Verify point structure
        assert point._name == "temperature"

    def test_json_payload_multiple_fields(self, mock_services):
        """Test processing JSON payload with multiple fields."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "environment",
                        "topic": "test/+/data",
                        "fields": {
                            "temperature": "$.payload.temperature",
                            "humidity": "$.payload.humidity",
                            "pressure": "$.payload.pressure",
                        },
                        "tags": {"device_id": "$.topic[1]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/dev001/data"
        message.payload = json.dumps(
            {"temperature": 23.5, "humidity": 65.2, "pressure": 1013.25}
        ).encode()
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()


class TestTypeConversion:
    """Tests for type conversion in the flow."""

    def test_string_to_float_conversion(self, mock_services):
        """Test converting string value to float."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "typed",
                        "topic": "test/typed/+/value",
                        "fields": {
                            "float_val": {"value": "$.payload.raw", "type": "float"},
                        },
                        "tags": {"type": "$.topic[2]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/typed/float/value"
        message.payload = json.dumps({"raw": "123.456"}).encode()
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()

    def test_string_to_int_conversion(self, mock_services):
        """Test converting string value to int."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "typed",
                        "topic": "test/typed/+/value",
                        "fields": {
                            "int_val": {"value": "$.payload.raw", "type": "int"},
                        },
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/typed/int/value"
        message.payload = json.dumps({"raw": "789"}).encode()
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()


class TestExpressionEvaluation:
    """Tests for mathematical expression evaluation."""

    def test_celsius_to_fahrenheit(self, mock_services):
        """Test Celsius to Fahrenheit conversion expression."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "temperature",
                        "topic": "test/expr/temperature",
                        "fields": {
                            "celsius": "$.payload",
                            "fahrenheit": "= 32 + ($.payload * 9 / 5)",
                        },
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        # Test 0°C = 32°F
        message = MagicMock()
        message.topic = "test/expr/temperature"
        message.payload = b"0"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)
        mock_write.assert_called()
        mock_write.reset_mock()

        # Test 100°C = 212°F
        message.payload = b"100"
        bridge._on_mqtt_message(None, None, message)
        mock_write.assert_called()


class TestArrayAccess:
    """Tests for array access via JSONPath."""

    def test_array_index_extraction(self, mock_services):
        """Test extracting specific array elements."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "array_data",
                        "topic": "test/array/data",
                        "fields": {
                            "first": "$.payload.values[0]",
                            "second": "$.payload.values[1]",
                            "third": "$.payload.values[2]",
                        },
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/array/data"
        message.payload = json.dumps({"values": [10, 20, 30, 40, 50]}).encode()
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()


class TestWildcardTopics:
    """Tests for MQTT wildcard topic subscriptions."""

    def test_single_level_wildcard(self, mock_services):
        """Test + single-level wildcard."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "sensor",
                        "topic": "home/+/temperature",
                        "fields": {"value": "$.payload"},
                        "tags": {"room": "$.topic[1]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        # Test multiple rooms
        for room in ["living_room", "bedroom", "kitchen"]:
            message = MagicMock()
            message.topic = f"home/{room}/temperature"
            message.payload = b"22.5"
            message.qos = 0

            bridge._on_mqtt_message(None, None, message)

        assert mock_write.call_count == 3

    def test_multi_level_wildcard(self, mock_services):
        """Test # multi-level wildcard."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "wildcard",
                        "topic": "test/wild/#",
                        "fields": {"value": "$.payload"},
                        "tags": {"level1": "$.topic[2]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        # Test various depth levels
        topics = [
            "test/wild/level1",
            "test/wild/level1/level2",
            "test/wild/a/b/c",
        ]

        for topic in topics:
            message = MagicMock()
            message.topic = topic
            message.payload = b"100"
            message.qos = 0

            bridge._on_mqtt_message(None, None, message)

        assert mock_write.call_count == 3


class TestErrorHandling:
    """Tests for error handling in the flow."""

    def test_raw_string_payload_written(self, mock_services):
        """Test raw string payloads (non-JSON) are written to InfluxDB."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "power_state",
                        "topic": "stat/+/POWER",
                        "fields": {"value": "$.payload"},
                        "tags": {"device": "$.topic[1]"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "stat/device1/POWER"
        message.payload = b"ON"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        # Raw string payload should be written
        mock_write.assert_called_once()
        point = mock_write.call_args[0][0]
        assert point._name == "power_state"

    def test_missing_field_handled_gracefully(self, mock_services, caplog):
        """Test missing field is handled with warning."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test/#",
                        "fields": {
                            "temperature": "$.payload.temperature",
                            "humidity": "$.payload.humidity",
                        },
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        # Payload missing humidity field
        message = MagicMock()
        message.topic = "test/partial"
        message.payload = json.dumps({"temperature": 25.0}).encode()
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        # Should still write with available fields
        mock_write.assert_called_once()
        assert "Could not get value for field: humidity" in caplog.text

    def test_no_fields_no_write(self, mock_services, caplog):
        """Test no fields extracted means no write."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test/#",
                        "fields": {"value": "$.payload.nonexistent"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/empty"
        message.payload = b'{"other": 123}'
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_not_called()
        assert "No fields to write" in caplog.text

    def test_influxdb_write_error_handled(self, mock_services, caplog):
        """Test InfluxDB write error is handled gracefully."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test/#",
                        "fields": {"value": "$.payload"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write
        mock_write.side_effect = Exception("Connection refused")

        message = MagicMock()
        message.topic = "test/error"
        message.payload = b"25.5"
        message.qos = 0

        # Should not raise exception
        bridge._on_mqtt_message(None, None, message)

        assert "Failed to write to InfluxDB" in caplog.text


class TestCustomBucket:
    """Tests for per-point bucket configuration."""

    def test_custom_bucket_used(self, mock_services):
        """Test custom bucket is used when specified."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "default_bucket",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test/#",
                        "bucket": "custom_bucket",
                        "fields": {"value": "$.payload"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b"25.5"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args[1]
        assert call_kwargs["database"] == "custom_bucket"

    def test_default_bucket_used(self, mock_services):
        """Test default bucket is used when no custom bucket specified."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "default_bucket",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test/#",
                        "fields": {"value": "$.payload"},
                    }
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b"25.5"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args[1]
        assert call_kwargs["database"] == "default_bucket"


class TestHttpForwarding:
    """Tests for HTTP forwarding functionality."""

    def test_http_forward_called(self, mock_services):
        """Test HTTP forwarding is called when configured."""
        with patch("mqtt2influxdb.mqtt2influxdb.requests") as mock_requests:
            config = Config.model_validate(
                {
                    "mqtt": {"host": "localhost", "port": 1883},
                    "influxdb": {
                        "host": "localhost",
                    "port": 8181,
                        "token": "token",
                        "org": "org",
                        "bucket": "test",
                    },
                    "http": {
                        "destination": "http://example.com/api",
                        "action": "post",
                    },
                    "points": [
                        {
                            "measurement": "test",
                            "topic": "test/#",
                            "fields": {"value": "$.payload"},
                            "httpcontent": {"temp": "$.payload"},
                        }
                    ],
                }
            )

            bridge = Mqtt2InfluxDB(config)

            message = MagicMock()
            message.topic = "test/topic"
            message.payload = b"25.5"
            message.qos = 0

            bridge._on_mqtt_message(None, None, message)

            # Verify HTTP request was made
            mock_requests.post.assert_called_once()


class TestMultiplePoints:
    """Tests for multiple point configurations."""

    def test_multiple_points_same_topic(self, mock_services):
        """Test multiple points matching the same topic."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "test",
                },
                "points": [
                    {
                        "measurement": "measurement1",
                        "topic": "test/#",
                        "fields": {"value": "$.payload"},
                    },
                    {
                        "measurement": "measurement2",
                        "topic": "test/#",
                        "fields": {"doubled": "= $.payload * 2"},
                    },
                ],
            }
        )

        bridge = Mqtt2InfluxDB(config)
        mock_write = mock_services["influxdb"].return_value.write

        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b"10"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        # Both points should be written
        assert mock_write.call_count == 2
