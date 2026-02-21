#!/bin/sh
set -e

alembic -c alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
