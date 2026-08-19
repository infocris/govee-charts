#!/usr/bin/env bash
# Stop leftover foreground govee_charts.main processes (make run / serve / workers).
# Does not touch launchd/systemd units — only matching Python entrypoints.
set -euo pipefail

PATTERN='govee_charts\.main'
SELF_PID=$$
PARENT_PID=$PPID

pids=()
if command -v pgrep >/dev/null 2>&1; then
  # -f matches full command line; ignore our own make/shell parents.
  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    [ "$pid" = "$SELF_PID" ] && continue
    [ "$pid" = "$PARENT_PID" ] && continue
    pids+=("$pid")
  done < <(pgrep -f "$PATTERN" 2>/dev/null || true)
fi

if [ "${#pids[@]}" -eq 0 ]; then
  echo "No local govee_charts.main instance to stop."
  exit 0
fi

echo "Stopping local govee_charts instance(s): ${pids[*]}"
# Prefer SIGINT (same path as Ctrl+C / uvicorn), then SIGTERM.
kill -INT "${pids[@]}" 2>/dev/null || true
sleep 0.3
kill -TERM "${pids[@]}" 2>/dev/null || true

# Wait briefly for graceful shutdown (uvicorn / workers).
deadline=$((SECONDS + 8))
while [ "$SECONDS" -lt "$deadline" ]; do
  alive=()
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      alive+=("$pid")
    fi
  done
  if [ "${#alive[@]}" -eq 0 ]; then
    echo "Stopped."
    exit 0
  fi
  sleep 0.2
done

alive=()
for pid in "${pids[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    alive+=("$pid")
  fi
done
if [ "${#alive[@]}" -gt 0 ]; then
  echo "Force-killing: ${alive[*]}"
  kill -KILL "${alive[@]}" 2>/dev/null || true
fi
echo "Stopped."
