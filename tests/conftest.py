"""Shared test fixtures."""

import pytest

from mqtt2influxdb.config import Config


@pytest.fixture
def minimal_config_dict():
    """Minimal valid configuration dictionary."""
    return {
        "mqtt": {"host": "localhost", "port": 1883},
        "influxdb": {
            "host": "localhost",
            "port": 8181,
            "token": "test-token",
            "org": "test-org",
            "bucket": "test-bucket",
        },
        "points": [
            {
                "measurement": "temperature",
                "topic": "test/+/temperature",
                "fields": {"value": "$.payload"},
            }
        ],
    }


@pytest.fixture
def minimal_config(minimal_config_dict):
    """Minimal valid Config object."""
    return Config.model_validate(minimal_config_dict)


@pytest.fixture
def full_config_dict():
    """Full configuration dictionary with all options."""
    return {
        "mqtt": {
            "host": "localhost",
            "port": 1883,
            "username": "user",
            "password": "pass",
        },
        "influxdb": {
            "host": "localhost",
            "port": 8181,
            "token": "test-token",
            "org": "test-org",
            "bucket": "test-bucket",
            "enable_gzip": True,
        },
        "http": {
            "destination": "http://example.com/api",
            "action": "post",
            "username": "httpuser",
            "password": "httppass",
        },
        "base64decode": {"source": "$.payload.data", "target": "decoded"},
        "points": [
            {
                "measurement": "temperature",
                "topic": "node/+/thermometer/+/temperature",
                "bucket": "custom-bucket",
                "schedule": "* * * * *",
                "fields": {
                    "value": "$.payload",
                    "converted": {"value": "$.payload.raw", "type": "float"},
                    "calculated": "= 32 + ($.payload * 9 / 5)",
                },
                "tags": {"sensor_id": "$.topic[1]", "channel": "$.topic[3]"},
                "httpcontent": {"temp": "$.payload"},
            }
        ],
    }


@pytest.fixture
def sample_mqtt_message():
    """Sample parsed MQTT message structure."""
    return {
        "topic": ["test", "sensor1", "temperature"],
        "payload": 25.5,
        "timestamp": None,
        "qos": 0,
    }


@pytest.fixture
def json_mqtt_message():
    """Sample parsed MQTT message with JSON payload."""
    return {
        "topic": ["test", "device", "dev001", "data"],
        "payload": {"temperature": 23.5, "humidity": 65.2, "pressure": 1013.25},
        "timestamp": None,
        "qos": 0,
    }
