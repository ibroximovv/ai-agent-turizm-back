#!/usr/bin/env bash
#
# Deploy the current branch to this server.
#
#   cd /var/www/ai-agent-turizm-back && ./deploy/deploy.sh
#
# Safe to re-run. It refuses to start if a quality gate fails, so a broken
# commit never replaces a working process.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/var/www/ai-agent-turizm-back}"
BRANCH="${BRANCH:-main}"
PM2_APP="${PM2_APP:-turizm-back}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:3005/api/}"

cd "$APP_DIR"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31m!!  %s\033[0m\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------
step "Tekshiruvlar"
# --------------------------------------------------------------------------
[[ -f .env ]] || fail ".env topilmadi. .env.example dan nusxa oling va to'ldiring."
command -v uv  >/dev/null || fail "uv o'rnatilmagan: curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v pm2 >/dev/null || fail "pm2 o'rnatilmagan: npm install -g pm2"

if [[ -n "$(git status --porcelain)" ]]; then
    fail "Ishchi katalogda saqlanmagan o'zgarishlar bor. Avval ularni hal qiling."
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
echo "Joriy commit: $PREVIOUS_SHA"

# --------------------------------------------------------------------------
step "Kodni yangilash ($BRANCH)"
# --------------------------------------------------------------------------
git fetch --prune origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
echo "Yangi commit: $(git rev-parse HEAD)"

# --------------------------------------------------------------------------
step "Bog'liqliklar"
# --------------------------------------------------------------------------
uv sync --no-dev

# --------------------------------------------------------------------------
step "Konfiguratsiya tekshiruvi"
# --------------------------------------------------------------------------
# --deploy turns on the production-only checks (SECRET_KEY, ALLOWED_HOSTS, …).
# W004/W008 are nginx's job: it terminates TLS and does the redirect.
.venv/bin/python manage.py check --deploy --fail-level ERROR

# A migration that was never generated locally would otherwise be discovered
# at the first request, after the old process is already gone.
if ! .venv/bin/python manage.py makemigrations --check --dry-run >/dev/null; then
    fail "Yaratilmagan migratsiyalar bor. Lokalda makemigrations qilib, commit qiling."
fi

# --------------------------------------------------------------------------
step "Migratsiyalar"
# --------------------------------------------------------------------------
.venv/bin/python manage.py migrate --noinput

# --------------------------------------------------------------------------
step "Statik fayllar"
# --------------------------------------------------------------------------
.venv/bin/python manage.py collectstatic --noinput

# --------------------------------------------------------------------------
step "Jarayonni qayta ishga tushirish"
# --------------------------------------------------------------------------
mkdir -p logs

# Materials that were mid-conversion when the old process died stay stuck in
# `converting`; they are reported below so they can be retried from the panel.
STUCK="$(.venv/bin/python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from apps.catalog.models import Material
print(Material.objects.filter(status__in=["queued", "converting", "uploading"]).count())
PY
)"

if pm2 describe "$PM2_APP" >/dev/null 2>&1; then
    pm2 restart "$PM2_APP" --update-env
else
    pm2 start deploy/ecosystem.config.js
fi
pm2 save

# --------------------------------------------------------------------------
step "Health check"
# --------------------------------------------------------------------------
for attempt in $(seq 1 15); do
    if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
        echo "OK — $(curl -fsS "$HEALTH_URL")"
        if [[ "$STUCK" != "0" ]]; then
            printf '\n\033[1;33m!   %s ta material yarim yo'\''lda qolgan edi.\033[0m\n' "$STUCK"
            echo "    Adminkadan ularni tanlab 'Pipeline'\''ni qayta ishga tushirish' amalini bajaring."
        fi
        printf '\n\033[1;32m==> Deploy tugadi\033[0m\n'
        exit 0
    fi
    sleep 2
done

pm2 logs "$PM2_APP" --lines 40 --nostream || true
fail "Health check o'tmadi. Yuqoridagi loglarni tekshiring. Orqaga qaytarish:
    git reset --hard $PREVIOUS_SHA && uv sync --no-dev && pm2 restart $PM2_APP"
