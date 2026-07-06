#!/bin/sh
set -e
python -m app.db_init
exec "$@"
