#!/bin/bash
while true; do
  echo [Mon Sep 14 12:13:54 UTC 2026] Starting bot...
  # IMPORTANT: Never touch /venv in any way to preserve packages
  python /app/bot.py > /logs/output.log 2> /logs/error.log || echo Bot crashed with code 0
  echo [Mon Sep 14 12:13:54 UTC 2026] Bot stopped but container still running. Install packages or fix code.
  sleep 10
done
