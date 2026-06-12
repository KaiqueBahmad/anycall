#!/bin/bash
set -e
cd "$(dirname "$0")/.."   # -> repo root

# Force reinstall of local anycall-py without redownloading external dependencies
# This ensures manual `uv sync && uv run` in examples uses the current lib code
uv --project python sync --reinstall-package anycall-py
