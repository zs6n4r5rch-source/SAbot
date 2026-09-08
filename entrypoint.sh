#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head
echo "Loading SAbot owner UI hotfixes..."
python -c "import sitecustomize; sitecustomize._install_sabot_owner_hotfix()"
echo "Owner UI hotfixes loaded. Starting bot..."
python -c "import threading, owner_critical_hotfix; threading.Thread(target=owner_critical_hotfix.install, daemon=True).start()"
exec python -m app.main
