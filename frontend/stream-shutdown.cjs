// Preloaded into the Next.js server next to edge-headers.cjs (`node -r`, see start.sh and
// ecosystem.config.cjs): hangs up open live-update streams as soon as the server is told
// to stop.
//
// The browser's live stream (GET /api/v1/teams/<id>/events, proxied to FastAPI) never
// finishes by itself. On SIGTERM (docker stop, plain runner) or SIGINT (PM2 stopping or
// reloading a worker), Next stops accepting connections and then waits for every open
// request to finish, so a single open meeting tab would hold the worker until it is
// killed: PM2's kill_timeout, or Docker's 25 s stop_grace_period. Hanging up the streams
// lets Next exit as soon as the normal requests in flight are done, and the browser's
// EventSource reconnects (during a PM2 reload, to a worker that is still running). Same
// idea as the API's own shutdown hook (plan 3.12 item 8).
"use strict";

const http = require("node:http");
const { constants } = require("node:os");

const STREAM_PATH = /^\/api\/v1\/teams\/[^/?]+\/events(?:\?|$)/;
// The stream responses still open. Responses, not sockets: once a stream has ended, the
// browser may reuse its keep-alive connection for a normal request, which must finish.
const open = new Set();

const original = http.Server.prototype.emit;

http.Server.prototype.emit = function emit(event, req, res, ...rest) {
  if (event === "request" && req && res && STREAM_PATH.test(req.url || "")) {
    open.add(res);
    res.once("close", () => open.delete(res)); // finished, or the connection went away
  }
  return original.call(this, event, req, res, ...rest);
};

/** Hang up every open stream; normal requests are left to finish. */
function closeStreams() {
  for (const res of open) res.destroy();
  open.clear();
}

function onStopSignal(signal) {
  closeStreams();
  // Next installs its own SIGTERM/SIGINT handlers (close the server, then exit) only once
  // it is listening. Until then this is the only handler, and a handled signal no longer
  // ends the process, so a stop during start-up would be swallowed and the worker left
  // running until PM2 or Docker kills it. Exit the way Next does instead (130, 143).
  if (process.listenerCount(signal) === 1) process.exit(128 + constants.signals[signal]);
}

process.on("SIGTERM", onStopSignal);
process.on("SIGINT", onStopSignal);

module.exports = { closeStreams, openStreams: () => open.size };
