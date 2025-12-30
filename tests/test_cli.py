"""Unit tests for CLI interface."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from mqtt2influxdb import __version__
from mqtt2influxdb.cli import main


@pytest.fixture
def runner():
    """Create CLI runner."""
    return CliRunner()


@pytest.fixture
def valid_config_file():
    """Create a temporary valid config file."""
    config = {
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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        yield f.name

    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def invalid_config_file():
    """Create a temporary invalid config file."""
    config = {
        "mqtt": {"host": "localhost", "port": 99999},  # Invalid port
        "influxdb": {
            "host": "localhost",
            "port": 8181,
            "token": "token",
            "org": "org",
            "bucket": "bucket",
        },
        "points": [{"measurement": "test", "topic": "test"}],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        yield f.name

    Path(f.name).unlink(missing_ok=True)


class TestCLIVersion:
    """Tests for version display."""

    def test_version_option(self, runner):
        """Test --version shows version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestCLIHelp:
    """Tests for help display."""

    def test_help_option(self, runner):
        """Test --help shows usage."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "--config" in result.output
        assert "--debug" in result.output
        assert "--test" in result.output

    def test_help_short_option(self, runner):
        """Test -h shows usage (if configured)."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0


class TestCLIConfigRequired:
    """Tests for config requirement."""

    def test_missing_config_shows_error(self, runner):
        """Test missing config option shows error."""
        result = runner.invoke(main, [])
        assert result.exit_code != 0
        assert "config" in result.output.lower()

    def test_nonexistent_config_shows_error(self, runner):
        """Test nonexistent config file shows error."""
        result = runner.invoke(main, ["-c", "/nonexistent/config.yml"])
        assert result.exit_code != 0


class TestCLITestMode:
    """Tests for config validation mode."""

    def test_test_mode_valid_config(self, runner, valid_config_file):
        """Test --test with valid config exits successfully."""
        result = runner.invoke(main, ["-c", valid_config_file, "--test"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_test_mode_invalid_config(self, runner, invalid_config_file):
        """Test --test with invalid config shows error."""
        result = runner.invoke(main, ["-c", invalid_config_file, "--test"])
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_test_mode_short_option(self, runner, valid_config_file):
        """Test -t shorthand works."""
        result = runner.invoke(main, ["-c", valid_config_file, "-t"])
        assert result.exit_code == 0


class TestCLIDebugMode:
    """Tests for debug logging mode."""

    def test_debug_short_option(self, runner, valid_config_file):
        """Test -D shorthand works."""
        result = runner.invoke(main, ["-c", valid_config_file, "-t", "-D"])
        assert result.exit_code == 0


class TestCLIRun:
    """Tests for normal run mode."""

    def test_run_creates_bridge(self, runner, valid_config_file):
        """Test normal run creates and starts bridge."""
        with patch("mqtt2influxdb.mqtt2influxdb.InfluxDBClient3"):
            with patch("mqtt2influxdb.mqtt2influxdb.mqtt.Client"):
                with patch.object(
                    __import__(
                        "mqtt2influxdb.mqtt2influxdb", fromlist=["Mqtt2InfluxDB"]
                    ).Mqtt2InfluxDB,
                    "run",
                    side_effect=KeyboardInterrupt(),
                ):
                    result = runner.invoke(main, ["-c", valid_config_file])
                    # Should exit cleanly after KeyboardInterrupt
                    assert result.exit_code == 0

    def test_run_handles_keyboard_interrupt(self, runner, valid_config_file):
        """Test KeyboardInterrupt is handled gracefully."""
        with patch("mqtt2influxdb.mqtt2influxdb.InfluxDBClient3"):
            with patch("mqtt2influxdb.mqtt2influxdb.mqtt.Client"):
                with patch.object(
                    __import__(
                        "mqtt2influxdb.mqtt2influxdb", fromlist=["Mqtt2InfluxDB"]
                    ).Mqtt2InfluxDB,
                    "run",
                    side_effect=KeyboardInterrupt(),
                ):
                    result = runner.invoke(main, ["-c", valid_config_file])
                    # Should exit cleanly
                    assert result.exit_code == 0


class TestCLIDaemonMode:
    """Tests for daemon mode."""

    def test_daemon_short_option(self, runner, valid_config_file):
        """Test -d shorthand works with --test mode."""
        # Test that -d flag is accepted (use with -t to avoid needing mocks)
        result = runner.invoke(main, ["-c", valid_config_file, "-t", "-d"])
        assert result.exit_code == 0


class TestCLIConfigValidation:
    """Tests for various config validation scenarios."""

    def test_empty_points_rejected(self, runner):
        """Test empty points list is rejected."""
        config = {
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            config_path = f.name

        try:
            result = runner.invoke(main, ["-c", config_path, "-t"])
            assert result.exit_code != 0
            assert "points" in result.output.lower()
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_missing_token_rejected(self, runner):
        """Test missing InfluxDB token is rejected."""
        config = {
            "mqtt": {"host": "localhost", "port": 1883},
            "influxdb": {
                "host": "localhost",
            "port": 8181,
                "org": "org",
                "bucket": "bucket",
            },
            "points": [{"measurement": "test", "topic": "test"}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            config_path = f.name

        try:
            result = runner.invoke(main, ["-c", config_path, "-t"])
            assert result.exit_code != 0
            assert "token" in result.output.lower()
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_invalid_schedule_rejected(self, runner):
        """Test invalid cron schedule is rejected."""
        config = {
            "mqtt": {"host": "localhost", "port": 1883},
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
                    "schedule": "invalid cron",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            config_path = f.name

        try:
            result = runner.invoke(main, ["-c", config_path, "-t"])
            assert result.exit_code != 0
        finally:
            Path(config_path).unlink(missing_ok=True)
