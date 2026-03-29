#!/bin/bash
# AI Meeting Assistant 실행 스크립트
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
streamlit run "$SCRIPT_DIR/app.py" --server.port 8502
