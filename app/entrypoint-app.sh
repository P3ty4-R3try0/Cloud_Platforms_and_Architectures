#!/bin/sh
set -e
python load_data.py
exec gunicorn -w 2 -b 0.0.0.0:8000 --access-logfile - main:app
