#!/usr/bin/env bash
# One-command start for GitHub Codespaces, a cloud VM, or any machine with Docker.
#   bash scripts/start.sh
# Optional: ADMIN_EMAIL=... ADMIN_PASSWORD=... bash scripts/start.sh   (non-interactive)
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "Docker is not available in this environment."
  if [ -n "${CODESPACES:-}" ]; then
    echo "Fix (GitHub Codespaces):"
    echo "  1) run:  git pull"
    echo "  2) press Ctrl+Shift+P, type 'Rebuild Container', choose 'Codespaces: Rebuild Container'"
    echo "  3) after it reopens, run:  bash scripts/start.sh"
  else
    echo "Install Docker Desktop (https://www.docker.com/products/docker-desktop), start it, then run this script again."
  fi
  exit 1
fi

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  secret=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')
  sed "s|^JWT_SECRET=.*|JWT_SECRET=${secret}|" backend/.env > backend/.env.tmp && mv backend/.env.tmp backend/.env
  echo "Created backend/.env with a random JWT_SECRET (add API keys there later)."
fi

echo "Starting database, API, worker and web app (first run takes 5-10 minutes)..."
if [ -n "${NO_BUILD:-}" ]; then docker compose up -d --no-build; else docker compose up --build -d; fi

echo -n "Waiting for the API"
for _ in $(seq 1 100); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 3
done
echo
if ! curl -fs http://localhost:8000/health >/dev/null 2>&1; then
  echo "The API did not start. Last log lines:"; docker compose logs --tail 40 backend; exit 1
fi

users=$(docker compose exec -T backend python -c "from sqlalchemy import func, select; from app.db import SessionLocal; from app.models import User; print(SessionLocal().scalar(select(func.count()).select_from(User)))" </dev/null | tr -d '\r')
make_admin="y"
if [ "${users:-0}" != "0" ] && [ -z "${ADMIN_EMAIL:-}" ]; then
  read -rp "A login already exists. Create or reset an admin login? [y/N] " make_admin || make_admin="n"
fi
if [ "${make_admin,,}" = "y" ]; then
  email="${ADMIN_EMAIL:-}"; pw="${ADMIN_PASSWORD:-}"
  if [ -z "$email" ]; then read -rp "Your login email: " email || { echo "No email given"; exit 1; }; fi
  while [ -z "$pw" ] || [ ${#pw} -lt 10 ]; do
    [ -n "$pw" ] && echo "That password has only ${#pw} characters - please use at least 10."
    read -rp "Choose a password (at least 10 characters, visible as you type): " pw || { echo "No password given"; exit 1; }
  done
  docker compose exec -T backend python -m app.cli create-admin "$email" "$pw" </dev/null
fi

echo -n "Waiting for the web app"
for _ in $(seq 1 60); do
  if curl -fs -o /dev/null http://localhost:3000/login 2>/dev/null; then break; fi
  echo -n "."; sleep 3
done
echo
if [ -n "${CODESPACE_NAME:-}" ]; then
  url="https://${CODESPACE_NAME}-3000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
else
  url="http://localhost:3000"
fi
echo "=============================================================="
echo " Platform is running.  Open:  ${url}"
echo " (Codespaces: also listed in the PORTS tab, port 3000)"
echo " Stop:  docker compose stop      Restart later:  bash scripts/start.sh"
echo "=============================================================="
