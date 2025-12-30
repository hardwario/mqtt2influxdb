"""Unit tests for MQTT to InfluxDB bridge core logic."""

import base64
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mqtt2influxdb.config import Config
from mqtt2influxdb.mqtt2influxdb import Mqtt2InfluxDB


@pytest.fixture
def mock_influxdb():
    """Mock InfluxDB client."""
    with patch("mqtt2influxdb.mqtt2influxdb.InfluxDBClient3") as mock:
        yield mock


@pytest.fixture
def mock_mqtt():
    """Mock MQTT client."""
    with patch("mqtt2influxdb.mqtt2influxdb.mqtt.Client") as mock:
        yield mock


@pytest.fixture
def bridge(minimal_config, mock_influxdb, mock_mqtt):
    """Create Mqtt2InfluxDB instance with mocked dependencies."""
    return Mqtt2InfluxDB(minimal_config)


class TestMqtt2InfluxDBInit:
    """Tests for Mqtt2InfluxDB initialization."""

    def test_init_creates_influxdb_client(
        self, minimal_config, mock_influxdb, mock_mqtt
    ):
        """Test InfluxDB client is created with correct parameters."""
        Mqtt2InfluxDB(minimal_config)

        mock_influxdb.assert_called_once_with(
            host="localhost:8181",
            token="test-token",
            org="test-org",
            database="test-bucket",
            enable_gzip=False,
        )

    def test_init_creates_mqtt_client(self, minimal_config, mock_influxdb, mock_mqtt):
        """Test MQTT client is created."""
        Mqtt2InfluxDB(minimal_config)
        mock_mqtt.assert_called_once()

    def test_init_with_mqtt_auth(self, mock_influxdb, mock_mqtt):
        """Test MQTT client with authentication."""
        config = Config.model_validate(
            {
                "mqtt": {
                    "host": "localhost",
                    "port": 1883,
                    "username": "user",
                    "password": "pass",
                },
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "bucket",
                },
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test",
                        "fields": {"value": "$.payload"},
                    }
                ],
            }
        )
        bridge = Mqtt2InfluxDB(config)

        # Check username_pw_set was called
        mock_mqtt.return_value.username_pw_set.assert_called_once_with("user", "pass")


class TestParseMessage:
    """Tests for message parsing."""

    def test_parse_simple_json(self, bridge):
        """Test parsing simple JSON payload."""
        message = MagicMock()
        message.topic = "test/sensor1/temperature"
        message.payload = b"25.5"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["topic"] == ["test", "sensor1", "temperature"]
        assert result["payload"] == 25.5
        assert result["qos"] == 0

    def test_parse_object_json(self, bridge):
        """Test parsing JSON object payload."""
        message = MagicMock()
        message.topic = "test/device/data"
        message.payload = b'{"temperature": 23.5, "humidity": 65.2}'
        message.qos = 1

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"]["temperature"] == 23.5
        assert result["payload"]["humidity"] == 65.2

    def test_parse_empty_payload(self, bridge):
        """Test parsing empty payload converts to null."""
        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b""
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] is None

    def test_parse_raw_string_payload(self, bridge):
        """Test parsing raw string payload (non-JSON) keeps string as-is."""
        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b"OFF"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == "OFF"

    def test_parse_raw_string_on(self, bridge):
        """Test parsing ON string payload."""
        message = MagicMock()
        message.topic = "stat/device/POWER"
        message.payload = b"ON"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == "ON"

    def test_parse_raw_text_payload(self, bridge):
        """Test parsing plain text payload."""
        message = MagicMock()
        message.topic = "test/status"
        message.payload = b"Device is running"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == "Device is running"

    def test_parse_malformed_json_as_string(self, bridge):
        """Test malformed JSON is kept as raw string."""
        message = MagicMock()
        message.topic = "test/topic"
        message.payload = b"not valid json {"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == "not valid json {"

    def test_parse_array_json(self, bridge):
        """Test parsing JSON array payload."""
        message = MagicMock()
        message.topic = "test/array"
        message.payload = b"[1, 2, 3, 4, 5]"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == [1, 2, 3, 4, 5]

    def test_parse_string_json(self, bridge):
        """Test parsing JSON string payload."""
        message = MagicMock()
        message.topic = "test/string"
        message.payload = b'"hello world"'
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] == "hello world"

    def test_parse_null_json(self, bridge):
        """Test parsing null JSON payload."""
        message = MagicMock()
        message.topic = "test/null"
        message.payload = b"null"
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert result["payload"] is None


class TestGetValue:
    """Tests for value extraction."""

    def test_get_literal_value(self, bridge):
        """Test extracting literal string value."""
        msg = {"topic": ["test"], "payload": 25.5}
        result = bridge._get_value("static_value", msg)
        assert result == "static_value"

    def test_get_payload_value(self, bridge):
        """Test extracting payload value via JSONPath."""
        msg = {"topic": ["test"], "payload": 25.5}
        result = bridge._get_value("$.payload", msg)
        assert result == 25.5

    def test_get_nested_value(self, bridge):
        """Test extracting nested JSON value."""
        msg = {"topic": ["test"], "payload": {"temperature": 23.5, "humidity": 65}}
        result = bridge._get_value("$.payload.temperature", msg)
        assert result == 23.5

    def test_get_topic_segment(self, bridge):
        """Test extracting topic segment."""
        msg = {"topic": ["node", "sensor123", "temperature"], "payload": 25.5}
        result = bridge._get_value("$.topic[1]", msg)
        assert result == "sensor123"

    def test_get_array_element(self, bridge):
        """Test extracting array element."""
        msg = {"topic": ["test"], "payload": {"values": [10, 20, 30]}}
        result = bridge._get_value("$.payload.values[0]", msg)
        assert result == 10

    def test_get_bracket_notation_special_chars(self, bridge):
        """Test extracting field with special characters using bracket notation."""
        # Simulates air quality sensor with PM2.5 field
        msg = {
            "topic": ["test"],
            "payload": {"air_quality_sensor": {"pm2.5": 5, "pm10": 12}},
        }
        result = bridge._get_value("$.payload.air_quality_sensor['pm2.5']", msg)
        assert result == 5

    def test_get_bracket_notation_nested(self, bridge):
        """Test bracket notation with nested special character fields."""
        msg = {
            "topic": ["test"],
            "payload": {"sensor.data": {"value.raw": 42}},
        }
        result = bridge._get_value("$.payload['sensor.data']['value.raw']", msg)
        assert result == 42

    def test_get_expression_value(self, bridge):
        """Test evaluating expression."""
        msg = {"topic": ["test"], "payload": 0}

        # Celsius to Fahrenheit: 0°C = 32°F
        result = bridge._get_value("= 32 + ($.payload * 9 / 5)", msg)
        assert result == 32

    def test_get_expression_complex(self, bridge):
        """Test complex expression evaluation."""
        msg = {"topic": ["test"], "payload": 100}

        # 100°C = 212°F
        result = bridge._get_value("= 32 + ($.payload * 9 / 5)", msg)
        assert result == 212

    def test_get_missing_value(self, bridge):
        """Test extracting missing value returns None."""
        msg = {"topic": ["test"], "payload": {"temperature": 25}}
        result = bridge._get_value("$.payload.nonexistent", msg)
        assert result is None

    def test_get_empty_spec(self, bridge):
        """Test empty spec returns None."""
        msg = {"topic": ["test"], "payload": 25}
        result = bridge._get_value("", msg)
        assert result is None


class TestConvertType:
    """Tests for type conversion."""

    def test_convert_to_float(self, bridge):
        """Test converting to float."""
        assert bridge._convert_type("123.456", "float") == 123.456
        assert bridge._convert_type(123, "float") == 123.0
        assert bridge._convert_type("42", "float") == 42.0

    def test_convert_to_int(self, bridge):
        """Test converting to int."""
        assert bridge._convert_type("789", "int") == 789
        assert bridge._convert_type(42.0, "int") == 42
        assert bridge._convert_type(True, "int") == 1

    def test_convert_to_str(self, bridge):
        """Test converting to string."""
        assert bridge._convert_type(42, "str") == "42"
        assert bridge._convert_type(3.14, "str") == "3.14"
        assert bridge._convert_type(True, "str") == "True"

    def test_convert_to_bool(self, bridge):
        """Test converting to bool."""
        assert bridge._convert_type(1, "bool") is True
        assert bridge._convert_type(0, "bool") is False
        assert bridge._convert_type("hello", "bool") is True
        assert bridge._convert_type("", "bool") is False

    def test_convert_to_booltoint(self, bridge):
        """Test converting bool to int."""
        assert bridge._convert_type(True, "booltoint") == 1
        assert bridge._convert_type(False, "booltoint") == 0
        assert bridge._convert_type(1, "booltoint") == 1
        assert bridge._convert_type(0, "booltoint") == 0

    def test_convert_invalid_returns_none(self, bridge, caplog):
        """Test invalid conversion returns None."""
        result = bridge._convert_type("not a number", "int")
        assert result is None
        assert "Type conversion failed" in caplog.text


class TestGetTimestamp:
    """Tests for timestamp extraction."""

    def test_timestamp_from_payload(self, bridge):
        """Test extracting timestamp from payload."""
        msg = {"payload": {"timestamp": 1703808000}}  # 2023-12-29 00:00:00 UTC

        result = bridge._get_timestamp(msg)

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_timestamp_fallback_to_now(self, bridge):
        """Test fallback to current time when no timestamp in payload."""
        msg = {"payload": 25.5}

        result = bridge._get_timestamp(msg)

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        # Should be close to now
        assert (datetime.now(tz=timezone.utc) - result).total_seconds() < 1

    def test_timestamp_invalid_fallback(self, bridge):
        """Test fallback when timestamp is invalid."""
        msg = {"payload": {"timestamp": "invalid"}}

        result = bridge._get_timestamp(msg)

        assert isinstance(result, datetime)
        # Should fall back to now


class TestProcessPoint:
    """Tests for point processing."""

    def test_process_simple_point(self, minimal_config, mock_influxdb, mock_mqtt):
        """Test processing a simple point."""
        bridge = Mqtt2InfluxDB(minimal_config)
        mock_write = mock_influxdb.return_value.write

        msg = {
            "topic": ["test", "sensor1", "temperature"],
            "payload": 25.5,
            "timestamp": None,
            "qos": 0,
        }

        bridge._process_point(minimal_config.points[0], msg)

        # Verify write was called
        mock_write.assert_called_once()

    def test_process_point_no_fields(
        self, minimal_config, mock_influxdb, mock_mqtt, caplog
    ):
        """Test processing point with no extractable fields logs warning."""
        bridge = Mqtt2InfluxDB(minimal_config)

        msg = {
            "topic": ["test", "sensor1", "temperature"],
            "payload": None,  # No valid payload
            "timestamp": None,
            "qos": 0,
        }

        bridge._process_point(minimal_config.points[0], msg)

        assert "No fields to write" in caplog.text


class TestBase64Decode:
    """Tests for base64 decoding functionality."""

    def test_base64_decode(self, mock_influxdb, mock_mqtt):
        """Test base64 decoding in message parsing."""
        config = Config.model_validate(
            {
                "mqtt": {"host": "localhost", "port": 1883},
                "influxdb": {
                    "host": "localhost",
                    "port": 8181,
                    "token": "token",
                    "org": "org",
                    "bucket": "bucket",
                },
                "base64decode": {"source": "$.payload.data", "target": "decoded"},
                "points": [
                    {
                        "measurement": "test",
                        "topic": "test",
                        "fields": {"value": "$.payload"},
                    }
                ],
            }
        )
        bridge = Mqtt2InfluxDB(config)

        # Create message with base64-encoded data
        encoded = base64.b64encode(b"Hello, World!").decode()
        message = MagicMock()
        message.topic = "test"
        message.payload = json.dumps({"data": encoded}).encode()
        message.qos = 0

        result = bridge._parse_message(message)

        assert result is not None
        assert "base64decoded" in result
        assert result["base64decoded"]["decoded"]["raw"] == b"Hello, World!"
        assert result["base64decoded"]["decoded"]["hex"] == b"Hello, World!".hex()


class TestMqttCallbacks:
    """Tests for MQTT callbacks."""

    def test_on_connect_subscribes_to_topics(
        self, minimal_config, mock_influxdb, mock_mqtt
    ):
        """Test on_connect subscribes to configured topics."""
        bridge = Mqtt2InfluxDB(minimal_config)

        # Simulate successful connection
        mock_client = MagicMock()
        mock_reason_code = MagicMock()
        mock_reason_code.is_failure = False

        bridge._on_mqtt_connect(mock_client, None, None, mock_reason_code, None)

        mock_client.subscribe.assert_called_once_with("test/+/temperature", qos=0)

    def test_on_connect_failure(self, minimal_config, mock_influxdb, mock_mqtt, caplog):
        """Test on_connect handles connection failure."""
        bridge = Mqtt2InfluxDB(minimal_config)

        mock_client = MagicMock()
        mock_reason_code = MagicMock()
        mock_reason_code.is_failure = True

        bridge._on_mqtt_connect(mock_client, None, None, mock_reason_code, None)

        # Should not subscribe on failure
        mock_client.subscribe.assert_not_called()
        assert "Connection failed" in caplog.text


class TestTopicMatching:
    """Tests for MQTT topic matching."""

    def test_wildcard_plus_matches(self, minimal_config, mock_influxdb, mock_mqtt):
        """Test + wildcard matches single level."""
        bridge = Mqtt2InfluxDB(minimal_config)

        # The topic pattern is "test/+/temperature"
        message = MagicMock()
        message.topic = "test/sensor1/temperature"
        message.payload = b"25.5"
        message.qos = 0

        # This should process the message
        bridge._on_mqtt_message(None, None, message)

        # Verify InfluxDB write was called
        mock_influxdb.return_value.write.assert_called()

    def test_non_matching_topic_ignored(self, minimal_config, mock_influxdb, mock_mqtt):
        """Test non-matching topic is ignored."""
        bridge = Mqtt2InfluxDB(minimal_config)

        message = MagicMock()
        message.topic = "other/sensor1/humidity"  # Different topic
        message.payload = b"65.0"
        message.qos = 0

        bridge._on_mqtt_message(None, None, message)

        # Verify InfluxDB write was NOT called
        mock_influxdb.return_value.write.assert_not_called()
