"""Command-line interface for mqtt2influxdb."""

import logging
import sys
from pathlib import Path
from time import sleep

import click

from . import __version__
from .config import ConfigError, load_config

LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s"


@click.command()
@click.option(
    "-c",
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to configuration file (YAML format).",
)
@click.option(
    "-D",
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
@click.option(
    "-o",
    "--output",
    "log_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Log output file path (default: stdout).",
)
@click.option(
    "-t",
    "--test",
    is_flag=True,
    default=False,
    help="Validate configuration without running.",
)
@click.option(
    "-d",
    "--daemon",
    is_flag=True,
    default=False,
    help="Daemon mode: retry on error instead of exiting.",
)
@click.version_option(version=__version__, prog_name="mqtt2influxdb")
def main(
    config_path: Path,
    debug: bool,
    log_file: Path | None,
    test: bool,
    daemon: bool,
) -> None:
    """MQTT to InfluxDB v3 bridge with flexible JSONPath transformation.

    Subscribes to MQTT topics and writes data points to InfluxDB v3.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=LOG_FORMAT,
        filename=str(log_file) if log_file else None,
    )

    try:
        with open(config_path) as f:
            config = load_config(f)

        if test:
            click.echo("Configuration file is valid.")
            return

        # Import here to avoid circular imports and speed up --help
        from .mqtt2influxdb import Mqtt2InfluxDB

        while True:
            try:
                bridge = Mqtt2InfluxDB(config)
                bridge.run()
            except KeyboardInterrupt:
                logging.info("Shutting down...")
                return
            except Exception as e:
                if not daemon:
                    raise
                logging.error("Error: %s", e)
                logging.info("Retrying in 30 seconds...")
                sleep(30)

    except ConfigError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        if debug:
            raise
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
