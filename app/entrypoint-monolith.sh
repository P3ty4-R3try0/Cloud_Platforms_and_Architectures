#!/bin/sh
set -e
redis-server --daemonize yes --save "" --appendonly no
until redis-cli ping >/dev/null 2>&1; do sleep 0.2; done
python load_data.py
exec gunicorn -w 2 -b 0.0.0.0:8000 --access-logfile - main:app
