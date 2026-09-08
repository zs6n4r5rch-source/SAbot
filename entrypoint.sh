#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head
echo "Loading SAbot owner UI hotfixes..."
python -c "import sitecustomize; sitecustomize._install_sabot_owner_hotfix()"
echo "Starting bot..."
python -m app.main &
APP_PID=$!
(
  sleep 2
  echo "Loading SAbot critical stock hotfix..."
  python -c "import owner_critical_hotfix; owner_critical_hotfix.install()"
) &
wait $APP_PID
