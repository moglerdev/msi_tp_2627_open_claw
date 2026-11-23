#!/usr/bin/env bash
# Starts the pseudonymization proxy on :9112 (next to the PII service on :9111).
# Crontab:  @reboot sleep 60 && $HOME/pseudo-start.sh
# Adjust paths below to where proxy.py is installed.
set -u
PIDF=$HOME/pseudo-proxy.pid
[ -f "$PIDF" ] && kill "$(cat "$PIDF")" 2>/dev/null && sleep 1
export PSEUDO_PORT=9112
export PSEUDO_UPSTREAM=https://openrouter.ai/api/v1
export PSEUDO_PII_URL=http://127.0.0.1:9111
export PSEUDO_ROLES=user,assistant,tool
# Fallback inside the proxy so Hermes does not fall back to its own direct (plain-text)
# chain on a 429. Model names rot (free tiers disappear); re-check them regularly.
export PSEUDO_FALLBACK_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,particle-ai/particle-1:free,recursive/flint-v1.0:free,baidu/ernie-5.5-flash-preview:free,dots-studio/dots-3-note-preview:free
# Audit log: what reached the upstream (pseudonymized); evaluate with audit.py.
# Debug UI at http://<host>:9112/ui/. "*" allows every client IP -- only do this on a
# host reachable from a trusted network (VPN), otherwise set a client list (default: localhost).
export PSEUDO_DEBUG_ALLOW="*"
export PSEUDO_AUDIT=1 PSEUDO_AUDIT_DIR=$HOME/pseudo-audit PSEUDO_AUDIT_DAYS=30
nohup python3 -I "$HOME/pseudo-proxy.py" >>"$HOME/pseudo-proxy.log" 2>&1 &
echo $! >"$PIDF"
sleep 2
curl -s localhost:9112/health; echo
