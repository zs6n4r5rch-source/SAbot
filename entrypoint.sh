#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head
echo "Loading SAbot owner UI hotfixes..."
python -c "import sitecustomize; sitecustomize._install_sabot_owner_hotfix()"
echo "Owner UI hotfixes loaded. Starting bot..."
exec python -m app.main
