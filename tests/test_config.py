"""Unit tests for configuration validation."""

from io import StringIO

import pytest
from pydantic import ValidationError

from mqtt2influxdb.config import (
    CRONTAB_REGEX,
    Base64DecodeConfig,
    Config,
    ConfigError,
    FieldConfig,
    HttpConfig,
    InfluxDBConfig,
    MqttConfig,
    PointConfig,
    load_config,
    validate_jsonpath,
    validate_value_spec,
)


class TestMqttConfig:
    """Tests for MQTT configuration model."""

    def test_minimal_config(self):
        """Test minimal MQTT config with required fields only."""
        config = MqttConfig(host="localhost", port=1883)
        assert config.host == "localhost"
        assert config.port == 1883
        assert config.username is None
        assert config.password is None

    def test_full_config(self):
        """Test MQTT config with all fields."""
        config = MqttConfig(
            host="mqtt.example.com",
            port=8883,
            username="user",
            password="secret",
        )
        assert config.host == "mqtt.example.com"
        assert config.port == 8883
        assert config.username == "user"
        assert config.password == "secret"

    def test_port_validation_min(self):
        """Test port minimum value validation."""
        config = MqttConfig(host="localhost", port=0)
        assert config.port == 0

    def test_port_validation_max(self):
        """Test port maximum value validation."""
        config = MqttConfig(host="localhost", port=65535)
        assert config.port == 65535

    def test_port_validation_invalid_negative(self):
        """Test port validation rejects negative values."""
        with pytest.raises(ValidationError) as exc_info:
            MqttConfig(host="localhost", port=-1)
        assert "port" in str(exc_info.value)

    def test_port_validation_invalid_too_high(self):
        """Test port validation rejects values > 65535."""
        with pytest.raises(ValidationError) as exc_info:
            MqttConfig(host="localhost", port=99999)
        assert "port" in str(exc_info.value)

    def test_empty_host_rejected(self):
        """Test empty host is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MqttConfig(host="", port=1883)
        assert "host" in str(exc_info.value)

    def test_extra_fields_rejected(self):
        """Test extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MqttConfig(host="localhost", port=1883, unknown="value")
        assert "extra" in str(exc_info.value).lower()


class TestInfluxDBConfig:
    """Tests for InfluxDB v3 configuration model."""

    def test_minimal_config(self):
        """Test minimal InfluxDB config."""
        config = InfluxDBConfig(
            host="localhost",
            token="my-token",
            org="my-org",
            bucket="my-bucket",
        )
        assert config.host == "localhost"
        assert config.port == 8181
        assert config.token == "my-token"
        assert config.org == "my-org"
        assert config.bucket == "my-bucket"
        assert config.enable_gzip is False

    def test_with_gzip(self):
        """Test InfluxDB config with gzip enabled."""
        config = InfluxDBConfig(
            host="localhost",
            token="token",
            org="org",
            bucket="bucket",
            enable_gzip=True,
        )
        assert config.enable_gzip is True

    def test_missing_token(self):
        """Test missing token is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InfluxDBConfig(
                host="localhost",
                org="org",
                bucket="bucket",
            )
        assert "token" in str(exc_info.value)

    def test_missing_org(self):
        """Test missing org is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InfluxDBConfig(
                host="localhost",
                token="token",
                bucket="bucket",
            )
        assert "org" in str(exc_info.value)

    def test_empty_bucket_rejected(self):
        """Test empty bucket is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InfluxDBConfig(
                host="localhost",
                token="token",
                org="org",
                bucket="",
            )
        assert "bucket" in str(exc_info.value)


class TestHttpConfig:
    """Tests for HTTP forwarding configuration."""

    def test_minimal_config(self):
        """Test minimal HTTP config."""
        config = HttpConfig(
            destination="http://example.com/api",
            action="post",
        )
        assert config.destination == "http://example.com/api"
        assert config.action == "post"
        assert config.username is None
        assert config.password is None

    def test_with_auth(self):
        """Test HTTP config with authentication."""
        config = HttpConfig(
            destination="http://example.com/api",
            action="post",
            username="user",
            password="pass",
        )
        assert config.username == "user"
        assert config.password == "pass"


class TestBase64DecodeConfig:
    """Tests for base64 decode configuration."""

    def test_config(self):
        """Test base64 decode config."""
        config = Base64DecodeConfig(source="$.payload.data", target="decoded")
        assert config.source == "$.payload.data"
        assert config.target == "decoded"


class TestFieldConfig:
    """Tests for field configuration."""

    def test_minimal_config(self):
        """Test minimal field config."""
        config = FieldConfig(value="$.payload")
        assert config.value == "$.payload"
        assert config.type is None

    def test_with_type(self):
        """Test field config with type."""
        config = FieldConfig(value="$.payload.raw", type="float")
        assert config.value == "$.payload.raw"
        assert config.type == "float"


class TestPointConfig:
    """Tests for measurement point configuration."""

    def test_minimal_config(self):
        """Test minimal point config."""
        config = PointConfig(
            measurement="temperature",
            topic="test/+/temperature",
            fields={"value": "$.payload"},
        )
        assert config.measurement == "temperature"
        assert config.topic == "test/+/temperature"
        assert config.bucket is None
        assert config.schedule is None
        assert config.fields == {"value": "$.payload"}
        assert config.tags == {}

    def test_full_config(self):
        """Test full point config."""
        config = PointConfig(
            measurement="temperature",
            topic="node/+/thermometer/+/temperature",
            bucket="custom-bucket",
            schedule="0 * * * *",
            fields={"value": "$.payload"},
            tags={"sensor_id": "$.topic[1]"},
        )
        assert config.bucket == "custom-bucket"
        assert config.schedule == "0 * * * *"
        assert config.fields == {"value": "$.payload"}
        assert config.tags == {"sensor_id": "$.topic[1]"}

    def test_valid_schedules(self):
        """Test various valid cron schedule formats."""
        valid_schedules = [
            "* * * * *",  # Every minute
            "0 * * * *",  # Every hour
            "*/5 * * * *",  # Every 5 minutes
            "0 9 * * 1-5",  # Weekdays at 9 AM
            "30 14 * * *",  # 2:30 PM daily
            "0 0 1 * *",  # First day of month
            "0,30 * * * *",  # Every half hour
        ]
        for schedule in valid_schedules:
            config = PointConfig(
                measurement="test",
                topic="test",
                schedule=schedule,
                fields={"value": "$.payload"},
            )
            assert config.schedule == schedule

    def test_invalid_schedule(self):
        """Test invalid cron schedule is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PointConfig(
                measurement="test",
                topic="test",
                schedule="invalid",
                fields={"value": "$.payload"},
            )
        assert "cron" in str(exc_info.value).lower()

    def test_measurement_jsonpath(self):
        """Test measurement with JSONPath is validated."""
        config = PointConfig(
            measurement="$.payload.type",
            topic="test",
            fields={"value": "$.payload"},
        )
        assert config.measurement == "$.payload.type"

    def test_invalid_measurement_jsonpath(self):
        """Test invalid JSONPath in measurement is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PointConfig(
                measurement="$.invalid[",
                topic="test",
                fields={"value": "$.payload"},
            )
        assert "JSONPath" in str(exc_info.value)


class TestConfig:
    """Tests for root configuration model."""

    def test_minimal_config(self, minimal_config_dict):
        """Test minimal valid configuration."""
        config = Config.model_validate(minimal_config_dict)
        assert config.mqtt.host == "localhost"
        assert config.influxdb.bucket == "test-bucket"
        assert len(config.points) == 1

    def test_full_config(self, full_config_dict):
        """Test full configuration with all options."""
        config = Config.model_validate(full_config_dict)
        assert config.mqtt.username == "user"
        assert config.influxdb.enable_gzip is True
        assert config.http.destination == "http://example.com/api"
        assert config.base64decode.target == "decoded"

    def test_empty_points_rejected(self):
        """Test empty points list is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "mqtt": {"host": "localhost", "port": 1883},
                    "influxdb": {
                        "host": "localhost",
                        "port": 8181,
                        "token": "token",
                        "org": "org",
                        "bucket": "bucket",
                    },
                    "points": [],
                }
            )
        assert "points" in str(exc_info.value)

    def test_missing_mqtt_rejected(self):
        """Test missing MQTT section is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "influxdb": {
                        "host": "localhost",
                        "port": 8181,
                        "token": "token",
                        "org": "org",
                        "bucket": "bucket",
                    },
                    "points": [{"measurement": "test", "topic": "test"}],
                }
            )
        assert "mqtt" in str(exc_info.value)

    def test_missing_influxdb_rejected(self):
        """Test missing InfluxDB section is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "mqtt": {"host": "localhost", "port": 1883},
                    "points": [{"measurement": "test", "topic": "test"}],
                }
            )
        assert "influxdb" in str(exc_info.value)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_yaml(self, minimal_config_dict):
        """Test loading valid YAML configuration."""
        import yaml

        yaml_content = yaml.dump(minimal_config_dict)
        config = load_config(StringIO(yaml_content))
        assert isinstance(config, Config)
        assert config.mqtt.host == "localhost"

    def test_load_empty_file(self):
        """Test loading empty file raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config(StringIO(""))
        assert "Empty" in str(exc_info.value)

    def test_load_invalid_yaml(self):
        """Test loading invalid YAML raises ConfigError."""
        with pytest.raises(ConfigError):
            load_config(StringIO("invalid: yaml: content:"))


class TestValidateJsonpath:
    """Tests for JSONPath validation."""

    def test_valid_jsonpath(self):
        """Test valid JSONPath expressions."""
        result = validate_jsonpath("$.payload")
        assert result is not None

    def test_nested_jsonpath(self):
        """Test nested JSONPath expressions."""
        result = validate_jsonpath("$.payload.temperature")
        assert result is not None

    def test_array_jsonpath(self):
        """Test array index JSONPath."""
        result = validate_jsonpath("$.payload.values[0]")
        assert result is not None

    def test_topic_jsonpath(self):
        """Test topic segment JSONPath."""
        result = validate_jsonpath("$.topic[1]")
        assert result is not None

    def test_literal_string(self):
        """Test literal string (no JSONPath) is returned as-is."""
        result = validate_jsonpath("static_value")
        assert result == "static_value"

    def test_invalid_jsonpath(self):
        """Test invalid JSONPath raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_jsonpath("$.invalid[")
        assert "JSONPath" in str(exc_info.value)


class TestValidateValueSpec:
    """Tests for value specification validation."""

    def test_jsonpath_spec(self):
        """Test JSONPath specification."""
        result = validate_value_spec("$.payload")
        assert result is not None

    def test_expression_spec(self):
        """Test expression specification."""
        result = validate_value_spec("= 32 + ($.payload * 9 / 5)")
        assert result is not None

    def test_literal_spec(self):
        """Test literal string specification."""
        result = validate_value_spec("static")
        assert result == "static"


class TestCrontabRegex:
    """Tests for crontab regex pattern."""

    def test_standard_patterns(self):
        """Test standard cron patterns match."""
        patterns = [
            "* * * * *",
            "0 0 * * *",
            "30 4 * * *",
            "0 22 * * 1-5",
            "*/15 * * * *",
            "0 9,17 * * *",
        ]
        for pattern in patterns:
            assert CRONTAB_REGEX.match(pattern), f"Pattern should match: {pattern}"

    def test_invalid_patterns(self):
        """Test clearly invalid cron patterns don't match."""
        patterns = [
            "invalid",
            "abc * * * *",  # Non-numeric
            "hello world",  # Completely invalid
        ]
        for pattern in patterns:
            assert not CRONTAB_REGEX.match(pattern), (
                f"Pattern should not match: {pattern}"
            )


class TestEnvironmentVariables:
    """Tests for environment variable substitution."""

    def test_env_var_substitution(self, monkeypatch):
        """Test ${VAR} substitution works."""
        monkeypatch.setenv("MQTT2INFLUXDB_INFLUXDB_TOKEN", "secret-token-123")

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: ${MQTT2INFLUXDB_INFLUXDB_TOKEN}
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.influxdb.token == "secret-token-123"

    def test_env_var_with_default(self, monkeypatch):
        """Test ${VAR:default} substitution uses default when var not set."""
        monkeypatch.delenv("MQTT2INFLUXDB_MQTT_HOST", raising=False)

        yaml_content = """
mqtt:
  host: ${MQTT2INFLUXDB_MQTT_HOST:localhost}
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.mqtt.host == "localhost"

    def test_env_var_with_default_override(self, monkeypatch):
        """Test ${VAR:default} uses env var value when set."""
        monkeypatch.setenv("MQTT2INFLUXDB_MQTT_HOST", "mqtt.example.com")

        yaml_content = """
mqtt:
  host: ${MQTT2INFLUXDB_MQTT_HOST:localhost}
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.mqtt.host == "mqtt.example.com"

    def test_env_var_empty_default(self, monkeypatch):
        """Test ${VAR:} uses empty string as default."""
        monkeypatch.delenv("MQTT2INFLUXDB_MQTT_USERNAME", raising=False)

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
  username: ${MQTT2INFLUXDB_MQTT_USERNAME:}
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        # Empty string should fail min_length=1 validation
        with pytest.raises(ConfigError):
            load_config(StringIO(yaml_content))

    def test_env_var_missing_raises_error(self, monkeypatch):
        """Test missing required env var raises ConfigError."""
        monkeypatch.delenv("MQTT2INFLUXDB_INFLUXDB_TOKEN", raising=False)

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: ${MQTT2INFLUXDB_INFLUXDB_TOKEN}
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        with pytest.raises(ConfigError) as exc_info:
            load_config(StringIO(yaml_content))
        assert "MQTT2INFLUXDB_INFLUXDB_TOKEN" in str(exc_info.value)

    def test_multiple_env_vars_in_string(self, monkeypatch):
        """Test multiple env vars in one string."""
        monkeypatch.setenv("MQTT2INFLUXDB_HTTP_HOST", "api.example.com")
        monkeypatch.setenv("MQTT2INFLUXDB_HTTP_PORT", "443")

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
http:
  destination: https://${MQTT2INFLUXDB_HTTP_HOST}:${MQTT2INFLUXDB_HTTP_PORT}/api
  action: post
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.http.destination == "https://api.example.com:443/api"

    def test_env_var_influxdb_port(self, monkeypatch):
        """Test InfluxDB port from environment variable."""
        monkeypatch.setenv("MQTT2INFLUXDB_INFLUXDB_HOST", "influxdb.example.com")
        monkeypatch.setenv("MQTT2INFLUXDB_INFLUXDB_PORT", "8087")

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
influxdb:
  host: ${MQTT2INFLUXDB_INFLUXDB_HOST}
  port: ${MQTT2INFLUXDB_INFLUXDB_PORT:8181}
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.influxdb.host == "influxdb.example.com"
        assert config.influxdb.port == 8087

    def test_env_var_in_nested_config(self, monkeypatch):
        """Test env var substitution in nested structures."""
        monkeypatch.setenv("MQTT2INFLUXDB_HTTP_USERNAME", "api-user")
        monkeypatch.setenv("MQTT2INFLUXDB_HTTP_PASSWORD", "api-secret")

        yaml_content = """
mqtt:
  host: localhost
  port: 1883
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
http:
  destination: https://api.example.com
  action: post
  username: ${MQTT2INFLUXDB_HTTP_USERNAME}
  password: ${MQTT2INFLUXDB_HTTP_PASSWORD}
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.http.username == "api-user"
        assert config.http.password == "api-secret"

    def test_env_var_mqtt_port(self, monkeypatch):
        """Test MQTT port from environment variable."""
        monkeypatch.setenv("MQTT2INFLUXDB_MQTT_PORT", "8883")

        yaml_content = """
mqtt:
  host: localhost
  port: ${MQTT2INFLUXDB_MQTT_PORT:1883}
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.mqtt.port == 8883

    def test_env_var_mqtt_port_default(self, monkeypatch):
        """Test MQTT port uses default when env var not set."""
        monkeypatch.delenv("MQTT2INFLUXDB_MQTT_PORT", raising=False)

        yaml_content = """
mqtt:
  host: localhost
  port: ${MQTT2INFLUXDB_MQTT_PORT:1883}
influxdb:
  host: localhost
  port: 8181
  token: test-token
  org: test-org
  bucket: test-bucket
points:
  - measurement: test
    topic: test/#
    fields:
      value: $.payload
"""
        config = load_config(StringIO(yaml_content))
        assert config.mqtt.port == 1883
