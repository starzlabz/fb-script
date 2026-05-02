#!/bin/zsh
cd "$(dirname "$0")"
export SYSTEM_VERSION_COMPAT=0
./venv/bin/python desktop.py
