#!/usr/bin/env bash
# Runs Claude Code headless on the Sky Fix master prompt until the deadline, restarting if it exits early.
# Usage: tmux new -s skyfix 'bash ~/forge/skyfix_run_claude.sh'
set -u
cd "$HOME/forge" || exit 1
mkdir -p skyfix/logs
DEADLINE_HUMAN="${1:-$(date -d 'tomorrow 09:30' '+%Y-%m-%d %H:%M %Z' 2>/dev/null || date -v+1d '+%Y-%m-%d 09:30')}"
echo "$DEADLINE_HUMAN" > skyfix/.deadline_human
DEADLINE=$(date -d "$DEADLINE_HUMAN" +%s 2>/dev/null || date -d 'tomorrow 09:30' +%s)
command -v claude >/dev/null 2>&1 || { echo "claude CLI not found in PATH"; exit 1; }
rm -f skyfix/.ALL_DONE
run=0; fast=0
while [ "$(date +%s)" -lt "$DEADLINE" ] && [ ! -f skyfix/.ALL_DONE ]; do
  run=$((run+1)); remaining=$(( (DEADLINE - $(date +%s)) / 60 )); t0=$(date +%s)
  echo "=== Sky Fix Claude run $run — $(date) — ${remaining} min remaining ==="
  if [ "$run" -eq 1 ]; then
    claude -p "$(cat skyfix/MASTER_PROMPT_SKYFIX.md)" --dangerously-skip-permissions --output-format stream-json --verbose \
      >> skyfix/logs/claude_session.jsonl 2>> skyfix/logs/claude_session.err
  else
    claude -c -p "You were restarted (run $run). Re-read ~/forge/skyfix/MASTER_PROMPT_SKYFIX.md, then ~/forge/skyfix/WORKLOG.md. Continue the unfinished phases in order. Time remaining: ${remaining} minutes until $(cat skyfix/.deadline_human). If everything is complete, write MORNING_REPORT.md and touch ~/forge/skyfix/.ALL_DONE." \
      --dangerously-skip-permissions --output-format stream-json --verbose \
      >> skyfix/logs/claude_session.jsonl 2>> skyfix/logs/claude_session.err
  fi
  rc=$?; el=$(( $(date +%s) - t0 )); echo "=== run $run exited rc=$rc after ${el}s ==="
  if [ "$el" -lt 120 ]; then fast=$((fast+1)); else fast=0; fi
  if [ "$fast" -ge 3 ]; then echo "three fast exits; sleeping 10 min (check skyfix/logs/claude_session.err)"; sleep 600; fast=0; fi
  sleep 5
done
echo "Sky Fix loop finished at $(date). ALL_DONE=$([ -f skyfix/.ALL_DONE ] && echo yes || echo no)"
