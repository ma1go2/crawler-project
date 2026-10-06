#!/bin/sh
set -e

python manage.py collectstatic --noinput
python manage.py migrate --run-syncdb --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
