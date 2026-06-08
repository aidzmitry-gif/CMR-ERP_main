#!/usr/bin/env bash
# Поднять супер-проект CMR-ERP_main после клона (--recurse-submodules).
set -euo pipefail
git submodule update --init --recursive
python -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate 2>/dev/null || true
pip install -r requirements.txt -r requirements-dev.txt
if [ -d frontend ]; then ( cd frontend && npm install ); fi
echo "bootstrap: готово."
