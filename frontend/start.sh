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

case "${WEB_RUNNER:-pm2}" in
  pm2)
    # Checked here too: PM2 reports a config error but still exits 0.
    if ! printf '%s' "${WEB_INSTANCES:-2}" | grep -Eqx '[1-9][0-9]*|max'; then
      echo "WEB_INSTANCES must be a positive whole number or \"max\", got: ${WEB_INSTANCES}" >&2
      exit 64
    fi
    exec pm2-runtime --json ecosystem.config.cjs
    ;;
  node) exec node -r ./edge-headers.cjs -r ./stream-shutdown.cjs server.js ;;
  *)
    echo "WEB_RUNNER must be pm2 or node, got: ${WEB_RUNNER}" >&2
    exit 64
    ;;
esac
