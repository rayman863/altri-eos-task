// node --test edge-headers.test.cjs : a spoofed X-Forwarded-For never reaches the app.
"use strict";

require("./edge-headers.cjs");

const assert = require("node:assert/strict");
const http = require("node:http");
const { test } = require("node:test");

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(req.headers));
    });
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function get(port, headers) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: "127.0.0.1", port, path: "/", headers }, (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => resolve(JSON.parse(body)));
      })
      .on("error", reject);
  });
}

test("client-supplied forwarding headers are replaced by the TCP peer", async () => {
  const server = await serve();
  try {
    const seen = await get(server.address().port, {
      "X-Forwarded-For": "6.6.6.6, 7.7.7.7",
      "X-Real-IP": "8.8.8.8",
      Forwarded: "for=9.9.9.9",
      "X-Request-ID": "req_spoofed1",
    });
    assert.equal(seen["x-forwarded-for"], "127.0.0.1");
    assert.equal(seen["x-real-ip"], undefined);
    assert.equal(seen["forwarded"], undefined);
    assert.equal(seen["x-request-id"], undefined);
  } finally {
    server.close();
  }
});

test("requests without the header get the peer address too", async () => {
  const server = await serve();
  try {
    const seen = await get(server.address().port, {});
    assert.equal(seen["x-forwarded-for"], "127.0.0.1");
  } finally {
    server.close();
  }
});
