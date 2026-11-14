#!/bin/zsh
cd "$(dirname "$0")"
lsof -ti tcp:8765 | xargs kill 2>/dev/null
exec /usr/bin/python3 app.py
