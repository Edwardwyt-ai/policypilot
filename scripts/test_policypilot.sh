#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
if [[ "$SCRIPT_DIR" == "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="."
fi
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  echo "Error: no project Python found under .venv." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

usage() {
  printf '%s\n' \
    'Usage:' \
    '  bash scripts/test_policypilot.sh unit' \
    '  bash scripts/test_policypilot.sh eval TASK_ID [TASK_ID ...]' \
    '' \
    'Examples:' \
    '  bash scripts/test_policypilot.sh unit' \
    '  bash scripts/test_policypilot.sh eval task_001' \
    '  bash scripts/test_policypilot.sh eval task_001 task_010' \
    '' \
    'Optional environment overrides for eval:' \
    '  AGENT_MODEL, USER_MODEL, SEED, MAX_STEPS, MAX_ERRORS, SAVE_TO'
}

MODE="${1:-unit}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$MODE" in
  unit)
    if [[ $# -ne 0 ]]; then
      echo "Error: unit mode does not accept task IDs." >&2
      usage
      exit 2
    fi
    printf -v TIMESTAMP '%(%Y%m%d_%H%M%S)T' -1
    BASETEMP="$ROOT/.pytest-script-$TIMESTAMP"
    echo "[PolicyPilot] Running unit tests..."
    "$PYTHON" -m pytest tests/policypilot -q --basetemp "$BASETEMP"
    echo "[PolicyPilot] Running Ruff..."
    "$PYTHON" -m ruff check src/policypilot tests/policypilot scripts
    echo "[PolicyPilot] Running compile check..."
    "$PYTHON" -m compileall -q src/policypilot
    echo "[PolicyPilot] Unit verification passed."
    ;;

  eval)
    if [[ $# -eq 0 ]]; then
      echo "Error: eval mode requires at least one task ID." >&2
      usage
      exit 2
    fi
    TASK_IDS=("$@")
    AGENT_MODEL="${AGENT_MODEL:-deepseek/deepseek-chat}"
    USER_MODEL="${USER_MODEL:-deepseek/deepseek-chat}"
    SEED="${SEED:-0}"
    MAX_STEPS="${MAX_STEPS:-40}"
    MAX_ERRORS="${MAX_ERRORS:-10}"
    printf -v TIMESTAMP '%(%Y%m%d_%H%M%S)T' -1
    TASK_LABEL="$(IFS=_; echo "${TASK_IDS[*]}")"
    SAVE_TO="${SAVE_TO:-vscode_${TASK_LABEL}_seed${SEED}_${TIMESTAMP}}"

    echo "[PolicyPilot] This mode uses external model APIs and may incur cost."
    echo "[PolicyPilot] Tasks: ${TASK_IDS[*]}"
    echo "[PolicyPilot] Agent model: $AGENT_MODEL"
    echo "[PolicyPilot] User model: $USER_MODEL"
    echo "[PolicyPilot] Seed: $SEED"
    echo "[PolicyPilot] Output: data/simulations/$SAVE_TO"

    "$PYTHON" scripts/evaluate_v1.py \
      --task-ids "${TASK_IDS[@]}" \
      --agent-model "$AGENT_MODEL" \
      --user-model "$USER_MODEL" \
      --seed "$SEED" \
      --max-steps "$MAX_STEPS" \
      --max-errors "$MAX_ERRORS" \
      --save-to "$SAVE_TO"
    ;;

  help|-h|--help)
    usage
    ;;

  *)
    echo "Error: unknown mode '$MODE'." >&2
    usage
    exit 2
    ;;
esac
