#!/usr/bin/env python3

import os
import sys
import argparse
import logging
from time import sleep
from urllib3 import disable_warnings
from .config import load_config, ConfigError
from .mqtt2influxdb import Mqtt2InfluxDB
from . import __version__

LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'


def main():
    argp = argparse.ArgumentParser(description='MQTT to InfluxDB')
    argp.add_argument('-c', '--config', help='path to configuration file (YAML format)', required=True)
    argp.add_argument('-D', '--debug', help='print debug messages', action='store_true')
    argp.add_argument('-o', '--output', help='output log messages to file')
    argp.add_argument('-t', '--test', help='test parse config', action='store_true')
    argp.add_argument('-d', '--daemon', help='on connection error instead of exiting just wait for some time and try again', action='store_true')
    argp.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__)
    argp.add_argument('-w', '--warnings', help='disable urllib3 TLS warnings if you are sure', action='store_true')
    args = argp.parse_args()

    log_file = None
    if args.output:
        log_file = args.output

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format=LOG_FORMAT, filename=log_file)

    try:
        config = load_config(open(args.config, 'r'))

        if args.warnings:
            disable_warnings()

        if args.test:
            if args.debug:
                print(config)
            print("The configuration file seems ok")
            return

        try:
            m2i = Mqtt2InfluxDB(config)
            m2i.run()
        except KeyboardInterrupt:
            return
        except Exception as e:
            if not args.daemon:
                raise
            logging.error(e)
            logging.info('Suspending for 30 seconds')
            sleep(30)

    except Exception as e:
        if args.debug or os.getenv('DEBUG', False):
            raise e
        if isinstance(e, ConfigError):
            print('Config error:')
        print(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
