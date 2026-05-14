#!/bin/sh
# Run database migrations then hand off to gunicorn.
# This script is the Dockerfile entrypoint for all deployments.
set -e

echo "Running database migrations..."
FLASK_APP='app:create_app' FLASK_SKIP_SCHEDULER=1 flask db upgrade

echo "Starting gunicorn..."
exec gunicorn -c gunicorn.conf.py wsgi:app
