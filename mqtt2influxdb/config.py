"""Configuration models for mqtt2influxdb using Pydantic."""

import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

import jsonpath_ng
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .expr import parse_expression

# Regex for environment variable substitution: ${VAR} or ${VAR:default}
ENV_VAR_REGEX = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")

# Regex for schedule config entries (basic syntax validation)
CRONTAB_REGEX = re.compile(
    r"(?P<minute>\*|[0-5]?\d|\*/\d+|\d+-\d+|\d+(,\d+)*)\s+"
    r"(?P<hour>\*|[01]?\d|2[0-3]|\*/\d+|\d+-\d+|\d+(,\d+)*)\s+"
    r"(?P<day>\*|0?[1-9]|[12]\d|3[01]|\*/\d+|\d+-\d+|\d+(,\d+)*)\s+"
    r"(?P<month>\*|0?[1-9]|1[012]|\*/\d+|\d+-\d+|\d+(,\d+)*)\s+"
    r"(?P<day_of_week>\*|[0-6](-[0-6])?|\*/\d+|\d+(,\d+)*)"
)

# Valid MQTT topic pattern (no empty segments, valid wildcards)
MQTT_TOPIC_REGEX = re.compile(
    r"^(?:[^/#+]+|\+)(?:/(?:[^/#+]+|\+))*(?:/#)?$|"  # Normal topics with + and trailing #
    r"^#$"  # Just # is valid
)

# Allowed HTTP methods for forwarding
ALLOWED_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head"})

# Allowed field types for type conversion
ALLOWED_FIELD_TYPES = frozenset({"float", "int", "str", "bool", "booltoint"})


class ConfigError(Exception):
    """Configuration validation error."""

    pass


class MqttConfig(BaseModel):
    """MQTT broker configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=0, le=65535)
    username: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)
    cafile: Path | None = None
    certfile: Path | None = None
    keyfile: Path | None = None

    @field_validator("cafile", "certfile", "keyfile", mode="after")
    @classmethod
    def validate_file_exists(cls, v: Path | None) -> Path | None:
        if v is not None and not v.exists():
            raise ValueError(f"File not found: {v}")
        return v

    @model_validator(mode="after")
    def validate_tls_config(self) -> "MqttConfig":
        """Validate TLS certificate configuration consistency."""
        # If client cert is provided, key must also be provided (and vice versa)
        if self.certfile and not self.keyfile:
            raise ValueError("certfile requires keyfile to be set")
        if self.keyfile and not self.certfile:
            raise ValueError("keyfile requires certfile to be set")
        # If using client certs, CA file should typically be set
        if self.certfile and not self.cafile:
            logging.warning(
                "certfile/keyfile set without cafile - "
                "server certificate will not be verified"
            )
        return self


class InfluxDBConfig(BaseModel):
    """InfluxDB v3 configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., min_length=1, description="InfluxDB hostname")
    port: int = Field(default=8181, ge=0, le=65535, description="InfluxDB port")
    token: str = Field(..., min_length=1, description="API token")
    org: str = Field(..., min_length=1, description="Organization name")
    bucket: str = Field(..., min_length=1, description="Default bucket name")
    enable_gzip: bool = Field(default=False, description="Enable gzip compression")


class HttpConfig(BaseModel):
    """HTTP forwarding configuration."""

    model_config = ConfigDict(extra="forbid")

    destination: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    username: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)

    @field_validator("action", mode="after")
    @classmethod
    def validate_http_method(cls, v: str) -> str:
        """Validate HTTP method against allowed methods."""
        if v.lower() not in ALLOWED_HTTP_METHODS:
            allowed = ", ".join(sorted(ALLOWED_HTTP_METHODS))
            raise ValueError(f"Invalid HTTP method: {v}. Allowed: {allowed}")
        return v

    @model_validator(mode="after")
    def validate_auth_config(self) -> "HttpConfig":
        """Validate HTTP authentication configuration consistency."""
        if self.username and not self.password:
            raise ValueError("username requires password to be set")
        if self.password and not self.username:
            raise ValueError("password requires username to be set")
        return self


class Base64DecodeConfig(BaseModel):
    """Base64 decode configuration."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)


class FieldConfig(BaseModel):
    """Field with optional type conversion."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(..., min_length=1)
    type: str | None = Field(default=None, min_length=1)

    @field_validator("type", mode="after")
    @classmethod
    def validate_field_type(cls, v: str | None) -> str | None:
        """Validate field type against allowed types."""
        if v is not None and v not in ALLOWED_FIELD_TYPES:
            allowed = ", ".join(sorted(ALLOWED_FIELD_TYPES))
            raise ValueError(f"Invalid field type: {v}. Allowed: {allowed}")
        return v


class PointConfig(BaseModel):
    """Measurement point configuration."""

    model_config = ConfigDict(extra="forbid")

    measurement: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    bucket: str | None = Field(default=None, min_length=1)
    schedule: str | None = Field(default=None, min_length=1)
    qos: int = Field(default=0, ge=0, le=2, description="MQTT QoS level (0, 1, or 2)")
    fields: dict[str, str | FieldConfig] = Field(..., min_length=1)
    tags: dict[str, str] = Field(default_factory=dict)
    httpcontent: dict[str, str] = Field(default_factory=dict)

    @field_validator("topic", mode="after")
    @classmethod
    def validate_topic_pattern(cls, v: str) -> str:
        """Validate MQTT topic pattern syntax."""
        # Check for empty segments
        if "//" in v:
            raise ValueError(f"Invalid topic pattern (empty segment): {v}")
        # Check for invalid wildcard usage
        segments = v.split("/")
        for i, segment in enumerate(segments):
            # + must be alone in its segment
            if "+" in segment and segment != "+":
                raise ValueError(
                    f"Invalid topic pattern (+ must be alone in segment): {v}"
                )
            # # must be the last segment and alone
            if "#" in segment:
                if segment != "#" or i != len(segments) - 1:
                    raise ValueError(
                        f"Invalid topic pattern (# must be last and alone): {v}"
                    )
        logging.debug("Validated MQTT topic pattern: '%s'", v)
        return v

    @field_validator("schedule", mode="after")
    @classmethod
    def validate_schedule(cls, v: str | None) -> str | None:
        """Validate cron schedule syntax."""
        if v is not None:
            if not CRONTAB_REGEX.match(v):
                raise ValueError(f"Invalid cron format: {v}")
            # Additional semantic validation
            parts = v.split()
            if len(parts) == 5:
                minute, hour, day, month, dow = parts
                # Validate ranges make sense
                cls._validate_cron_range(day, 1, 31, "day")
                cls._validate_cron_range(month, 1, 12, "month")
                cls._validate_cron_range(dow, 0, 6, "day_of_week")
            logging.debug("Validated crontab entry: '%s'", v)
        return v

    @staticmethod
    def _validate_cron_range(value: str, min_val: int, max_val: int, name: str) -> None:
        """Validate individual cron field ranges."""
        if value == "*" or value.startswith("*/"):
            return
        # Handle ranges like 1-15
        if "-" in value and "," not in value:
            try:
                start, end = map(int, value.split("-"))
                if start > end:
                    raise ValueError(
                        f"Invalid cron {name} range: {start}-{end} (start > end)"
                    )
                if start < min_val or end > max_val:
                    raise ValueError(
                        f"Invalid cron {name} range: {value} (must be {min_val}-{max_val})"
                    )
            except ValueError as e:
                if "Invalid cron" in str(e):
                    raise
                # Not a simple range, skip validation
                pass

    @field_validator("measurement", mode="after")
    @classmethod
    def validate_measurement(cls, v: str) -> str:
        if "$." in v:
            try:
                jsonpath_ng.parse(v)
                logging.debug("Validated measurement as JSONPath: '%s'", v)
            except Exception as e:
                raise ValueError(f"Invalid JSONPath in measurement: {v}") from e
        return v


class Config(BaseModel):
    """Root configuration model."""

    model_config = ConfigDict(extra="forbid")

    mqtt: MqttConfig
    influxdb: InfluxDBConfig
    http: HttpConfig | None = None
    base64decode: Base64DecodeConfig | None = None
    points: list[PointConfig] = Field(..., min_length=1)


def validate_jsonpath(value: str) -> jsonpath_ng.JSONPath | str:
    """Parse and validate a JSONPath expression, or return string as-is."""
    if "$." in value:
        try:
            logging.debug("Validating as JSONPath: '%s'", value)
            return jsonpath_ng.parse(value)
        except Exception as e:
            raise ValueError(f"Invalid JSONPath: {value}") from e
    logging.debug("Validated as string: '%s'", value)
    return value


def validate_value_spec(value: str) -> Any:
    """Validate a value specification (string, JSONPath, or expression)."""
    if "=" in value:
        logging.debug("Validating as expression: '%s'", value)
        return parse_expression(value)
    return validate_jsonpath(value)


def _expand_env_vars(value: str) -> str:
    """Expand environment variables in a string.

    Supports ${VAR} and ${VAR:default} syntax.

    Args:
        value: String potentially containing ${VAR} or ${VAR:default} patterns.

    Returns:
        String with environment variables expanded.

    Raises:
        ConfigError: If a required environment variable is not set.
    """

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)

        if env_value is not None:
            return env_value
        if default is not None:
            return default

        raise ConfigError(f"Environment variable '{var_name}' is not set")

    return ENV_VAR_REGEX.sub(replacer, value)


def _expand_env_vars_recursive(data: Any) -> Any:
    """Recursively expand environment variables in configuration data.

    Args:
        data: Configuration data (dict, list, or scalar).

    Returns:
        Configuration data with environment variables expanded.
    """
    if isinstance(data, dict):
        return {k: _expand_env_vars_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_env_vars_recursive(item) for item in data]
    if isinstance(data, str):
        return _expand_env_vars(data)
    return data


def load_config(config_file) -> Config:
    """Load and validate configuration from YAML file.

    Supports environment variable substitution using ${VAR} or ${VAR:default}
    syntax in any string value.

    Args:
        config_file: File-like object containing YAML configuration.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If configuration is invalid or required env vars are missing.
    """
    try:
        data = yaml.safe_load(config_file)
        if data is None:
            raise ConfigError("Empty configuration file")
        data = _expand_env_vars_recursive(data)
        return Config.model_validate(data)
    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(str(e)) from e
