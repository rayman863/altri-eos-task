#!/bin/sh
# How the web container runs Next's standalone server (layer L2, plan 3.11):
#   WEB_RUNNER=pm2  (default) PM2 cluster mode, WEB_INSTANCES workers (ecosystem.config.cjs)
#   WEB_RUNNER=node one plain Node process (the layer switched off)
# Both preload edge-headers.cjs (Next is the edge for client addresses) and
# stream-shutdown.cjs (a stop signal hangs up open live streams, so stops are quick).
# `exec` so the runner is PID 1 and gets the container's SIGTERM directly.
set -eu

# Read per request by proxy.ts, where anything but "off" means on: check it here, so a typo
# such as "Off" stops the start instead of being silently ignored.
case "${CSP_MODE:-nonce}" in
  nonce | off) ;;
  *)
    echo "CSP_MODE must be nonce or off, got: ${CSP_MODE}" >&2
    exit 64
    ;;
esac

# PM2's JSON log lines carry the worker id (process_id), so the two workers can be told
# apart in one container's stream (layer L5); false gives PM2's plain lines. Read the way
# the API reads the same variable (pydantic), so one value means the same in both containers.
case "$(printf '%s' "${LOG_WORKER_TAGS:-true}" | tr '[:upper:]' '[:lower:]')" in
  true | 1 | yes | on | t | y) pm2_logs=--json ;;
  false | 0 | no | off | f | n) pm2_logs= ;;
  *)
    echo "LOG_WORKER_TAGS must be true or false, got: ${LOG_WORKER_TAGS}" >&2
    exit 64
    ;;
esac

case "${WEB_RUNNER:-pm2}" in
  pm2)
    # Checked here too: PM2 reports a config error but still exits 0.
    if ! printf '%s' "${WEB_INSTANCES:-2}" | grep -Eqx '[1-9][0-9]*|max'; then
      echo "WEB_INSTANCES must be a positive whole number or \"max\", got: ${WEB_INSTANCES}" >&2
      exit 64
    fi
    # shellcheck disable=SC2086 # empty or one flag, on purpose unquoted
    exec pm2-runtime $pm2_logs ecosystem.config.cjs
    ;;
  node) exec node -r ./edge-headers.cjs -r ./stream-shutdown.cjs server.js ;;
  *)
    echo "WEB_RUNNER must be pm2 or node, got: ${WEB_RUNNER}" >&2
    exit 64
    ;;
esac
