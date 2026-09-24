#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
if [[ "$SCRIPT_DIR" == "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="."
fi
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

usage() {
  printf '%s\n' \
    'Usage:' \
    '  bash scripts/commit_git.sh "COMMIT MESSAGE" [--push] [FILE ...]' \
    '' \
    'Examples:' \
    '  # Stage and commit every change in the repository.' \
    '  bash scripts/commit_git.sh "feat: add need evaluation gold set"' \
    '' \
    '  # Commit everything, then push the current branch.' \
    '  bash scripts/commit_git.sh "feat: add need evaluation gold set" --push' \
    '' \
    '  # Stage and commit only the listed paths.' \
    '  bash scripts/commit_git.sh "fix: update memory retrieval" \' \
    '    src/policypilot/memory tests/policypilot/test_memory.py' \
    '' \
    'Notes:' \
    '  --push     Push after a successful commit. If the branch has no upstream,' \
    '             the script creates one on origin.' \
    '  FILE ...   When omitted, the script runs git add -A. Existing staged changes' \
    '             are preserved and will also be included in the commit.'
}

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

MESSAGE="$1"
shift

if [[ -z "${MESSAGE//[[:space:]]/}" ]]; then
  echo "Error: commit message cannot be empty." >&2
  exit 2
fi

PUSH=false
FILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --push)
      PUSH=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      FILES+=("$@")
      break
      ;;
    -*)
      echo "Error: unknown option '$1'." >&2
      usage >&2
      exit 2
      ;;
    *)
      FILES+=("$1")
      ;;
  esac
  shift
done

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is not available in PATH." >&2
  exit 1
fi

if [[ ! -d "$ROOT/.git" ]]; then
  echo "Error: $ROOT is not a Git repository." >&2
  exit 1
fi

# -c is scoped to this invocation and avoids changing the user's global config.
if WIN_ROOT="$(pwd -W 2>/dev/null)"; then
  :
else
  WIN_ROOT="$ROOT"
fi
GIT=(
  git
  --no-pager
  -c "safe.directory=$WIN_ROOT"
  -c core.autocrlf=input
)

if [[ ${#FILES[@]} -gt 0 ]]; then
  echo "[Git] Staging selected paths:"
  printf '  %s\n' "${FILES[@]}"
  "${GIT[@]}" add -- "${FILES[@]}"
else
  echo "[Git] Staging all repository changes..."
  "${GIT[@]}" add -A
fi

if "${GIT[@]}" diff --cached --quiet; then
  echo "[Git] Nothing to commit."
  exit 0
fi

echo "[Git] Staged change summary:"
"${GIT[@]}" diff --cached --stat

echo "[Git] Checking staged diff..."
"${GIT[@]}" diff --cached --check

echo "[Git] Creating commit: $MESSAGE"
"${GIT[@]}" commit -m "$MESSAGE"

COMMIT_ID="$("${GIT[@]}" rev-parse --short HEAD)"
BRANCH="$("${GIT[@]}" branch --show-current)"
echo "[Git] Commit created: $COMMIT_ID on $BRANCH"

if [[ "$PUSH" == true ]]; then
  if [[ -z "$BRANCH" ]]; then
    echo "Error: cannot push while HEAD is detached." >&2
    exit 1
  fi
  if ! "${GIT[@]}" remote get-url origin >/dev/null 2>&1; then
    echo "Error: remote 'origin' is not configured." >&2
    exit 1
  fi

  if "${GIT[@]}" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' \
    >/dev/null 2>&1; then
    echo "[Git] Pushing $BRANCH to its upstream..."
    "${GIT[@]}" push
  else
    echo "[Git] Setting origin/$BRANCH as upstream and pushing..."
    "${GIT[@]}" push --set-upstream origin "$BRANCH"
  fi
fi
