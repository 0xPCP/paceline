#!/bin/sh
# Run database migrations then hand off to gunicorn.
# This script is the Dockerfile entrypoint for all deployments.
set -e

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn -w 4 -b "0.0.0.0:${PORT:-8000}" --timeout 60 --preload wsgi:app
