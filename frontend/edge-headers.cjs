// Preloaded into the Next.js server (`node -r ./edge-headers.cjs server.js`): Next is the
// edge of this stack, so nothing a browser sends about where it comes from can be trusted.
//
// The API believes `X-Forwarded-For` and `X-Request-ID` only from the `web` container
// (plan 3.15), and Next passes incoming request headers on, both from Server Components
// and through the /api rewrite. Without this, any browser could pick the client address
// the API logs and rate-limits by. So, before Next handles a request: the forwarded-for
// header becomes the TCP peer's address, and client-chosen request ids are dropped (the
// API mints one).
"use strict";

const http = require("node:http");

const original = http.Server.prototype.emit;

function peerAddress(socket) {
  const address = (socket && socket.remoteAddress) || "";
  return address.startsWith("::ffff:") ? address.slice(7) : address;
}

function sanitize(req) {
  const peer = peerAddress(req.socket);
  if (peer) req.headers["x-forwarded-for"] = peer;
  else delete req.headers["x-forwarded-for"];
  delete req.headers["x-real-ip"];
  delete req.headers["forwarded"];
  delete req.headers["x-request-id"];
}

http.Server.prototype.emit = function emit(event, req, ...rest) {
  if (event === "request" && req && req.headers) sanitize(req);
  return original.call(this, event, req, ...rest);
};

module.exports = { sanitize, peerAddress };
