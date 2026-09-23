#!/usr/bin/env bash
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$APP_DIR/multilut_controller.py" "$@"
