#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Bruk: $0 {test|prod}" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_name="$1"

case "$target_name" in
  test)
    target_dir="/opt/test-treningslogger"
    ;;
  prod)
    target_dir="/opt/treningslogger"
    ;;
  *)
    usage
    ;;
esac

mkdir -p "$target_dir"

rsync \
  --archive \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache/' \
  --exclude 'instance/' \
  --exclude '.env' \
  --exclude 'AGENTS.md' \
  --exclude 'deploy/' \
  --exclude 'scripts/' \
  --exclude 'Makefile' \
  "$repo_root/workout_logger" \
  "$repo_root/run.py" \
  "$repo_root/requirements.txt" \
  "$repo_root/gunicorn.conf.py" \
  "$target_dir/"

echo "Deployet til $target_dir"
