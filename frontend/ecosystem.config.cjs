// PM2 cluster mode for the Next.js server (layer L2, plan 3.11), used by start.sh as
// `pm2-runtime --json ecosystem.config.cjs`: pm2-runtime stays in the foreground and
// streams every worker's output to stdout, which is what a container needs (`pm2 start`
// would daemonize and the container would exit at once).
//
// Clustering is safe because the web server holds no state: the session is a signed
// cookie, data comes from FastAPI on every request, live updates come from FastAPI's SSE
// stream, and nothing uses Next's data cache or ISR, so workers can't disagree.
"use strict";

const path = require("node:path");

const preload = (file) => path.join(__dirname, file);

/** WEB_INSTANCES: a positive whole number, or "max" (one worker per CPU thread, which
 * inside a container means every host thread, so not the default). */
function instances(raw = "2") {
  if (raw === "max") return "max";
  if (/^[1-9]\d*$/.test(raw)) return Number(raw);
  throw new Error(`WEB_INSTANCES must be a positive whole number or "max", got "${raw}"`);
}

module.exports = {
  apps: [
    {
      name: "web",
      // Next's standalone server; the workers share port 3000 through Node's cluster module.
      script: path.join(__dirname, "server.js"),
      cwd: __dirname,
      exec_mode: "cluster",
      instances: instances(process.env.WEB_INSTANCES || undefined),
      // The same preloads as the plain runner (start.sh): Next is the edge for client
      // addresses, and a stop signal hangs up open live streams.
      node_args: ["-r", preload("edge-headers.cjs"), "-r", preload("stream-shutdown.cjs")],
      // A crashed worker comes back without restarting the container; a worker that keeps
      // crashing right after start is given up after 10 tries instead of looping forever.
      autorestart: true,
      min_uptime: 5000,
      max_restarts: 10,
      exp_backoff_restart_delay: 200,
      max_memory_restart: "512M",
      // On stop, PM2 sends SIGINT and waits this long before SIGKILL. Next exits on its
      // own well before that; the container's stop_grace_period (25 s) covers it.
      kill_timeout: 10000,
      // No PM2 monitoring agent in the workers (it patches http and talks to pm2.io).
      pmx: false,
      automation: false,
    },
  ],
};
