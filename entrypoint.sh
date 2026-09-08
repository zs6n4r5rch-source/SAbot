#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Loading SAbot owner UI hotfixes..."
python -c "import sitecustomize; sitecustomize._install_sabot_owner_hotfix()"
echo "Loading SAbot critical stock hotfix..."
python -c "import owner_critical_hotfix; owner_critical_hotfix.install()"
echo "Loading SAbot final owner hotfix..."
python -c "import owner_final_hotfix; owner_final_hotfix.install()"
echo "Owner UI hotfixes loaded. Starting bot..."
exec python -m app.main
