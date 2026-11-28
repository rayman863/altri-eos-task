// node --test stream-shutdown.test.cjs : a stop signal hangs up live streams at once, and
// the server can close while normal requests still finish.
"use strict";

const { openStreams } = require("./stream-shutdown.cjs");

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");
const { test } = require("node:test");

function serve() {
  return new Promise((resolve) => {
    let connections = 0;
    const server = http.createServer((req, res) => {
      if (req.url.endsWith("/events")) {
        // Like the proxied SSE stream: headers and a first chunk, then never an end.
        res.writeHead(200, { "content-type": "text/event-stream" });
        res.write("retry: 2000\n\n");
      } else if (req.url.endsWith("/events?ended=1")) {
        // A stream the API side ended (an API restart, say): the connection stays open.
        res.writeHead(200, { "content-type": "text/event-stream" });
        res.end("retry: 2000\n\n");
      } else {
        setTimeout(() => res.end("done"), 300); // a normal request still in flight
      }
    });
    server.on("connection", () => connections++);
    server.connections = () => connections;
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function request(port, path, onResponse, agent = false) {
  return http.get({ host: "127.0.0.1", port, path, agent }, onResponse);
}

function body(port, path, agent) {
  return new Promise((resolve, reject) => {
    request(
      port,
      path,
      (res) => {
        let text = "";
        res.on("data", (chunk) => (text += chunk));
        res.on("end", () => resolve([res.statusCode, text]));
      },
      agent,
    ).on("error", reject);
  });
}

/** Next's own stop handler, which a running server has (it closes the server, then exits). */
function nextIsListening(t) {
  const next = () => {};
  process.on("SIGTERM", next);
  process.on("SIGINT", next);
  t.after(() => {
    process.removeListener("SIGTERM", next);
    process.removeListener("SIGINT", next);
  });
}

test("SIGTERM hangs up open streams; normal requests finish and the server closes", { timeout: 5000 }, async (t) => {
  nextIsListening(t);
  const server = await serve();
  // If the hang-up regresses, fail instead of keeping the test process alive.
  t.after(() => server.closeAllConnections());
  const port = server.address().port;

  let stream;
  await new Promise((resolve) => {
    request(port, "/api/v1/teams/team_lead/events", (res) => {
      stream = res;
      res.on("error", () => {}); // "aborted" once it is hung up
      res.once("data", resolve);
    }).on("error", () => {});
  });
  const streamClosed = new Promise((resolve) => stream.once("close", resolve));
  const slow = body(port, "/api/v1/teams/team_lead/scorecard");
  assert.equal(openStreams(), 1);
  await new Promise((r) => setTimeout(r, 50)); // the normal request reaches the server

  const started = Date.now();
  const serverClosed = new Promise((resolve) => server.close(resolve)); // what Next does
  process.emit("SIGTERM", "SIGTERM");

  await streamClosed;
  assert.ok(Date.now() - started < 200, "the stream was hung up at once");
  assert.deepEqual(await slow, [200, "done"]);
  await serverClosed;
  assert.ok(Date.now() - started < 1000, "the server closed without waiting on the stream");
  assert.equal(openStreams(), 0);
});

test("a normal request on a connection whose stream already ended is left to finish", { timeout: 5000 }, async (t) => {
  nextIsListening(t);
  const server = await serve();
  t.after(() => server.closeAllConnections());
  const port = server.address().port;
  const agent = new http.Agent({ keepAlive: true, maxSockets: 1 });
  t.after(() => agent.destroy());

  assert.deepEqual(await body(port, "/api/v1/teams/team_lead/events?ended=1", agent), [
    200,
    "retry: 2000\n\n",
  ]);
  assert.equal(openStreams(), 0);
  const slow = body(port, "/api/v1/teams/team_lead/scorecard", agent);
  await new Promise((r) => setTimeout(r, 50));
  assert.equal(server.connections(), 1, "the browser reused the stream's connection");

  process.emit("SIGTERM", "SIGTERM");
  assert.deepEqual(await slow, [200, "done"]);
});

test("only live-stream paths are tracked", { timeout: 5000 }, async () => {
  const server = await serve();
  const port = server.address().port;
  try {
    await body(port, "/api/v1/teams/team_lead/events-archive");
    assert.equal(openStreams(), 0);
  } finally {
    server.close();
  }
});

// Before Next is listening, this module's handler is the only one, and a handled signal
// doesn't end a Node process by itself: the stop must still work.
for (const [signal, code] of [
  ["SIGTERM", 143],
  ["SIGINT", 130],
]) {
  test(`${signal} during start-up still ends the process (exit ${code})`, { timeout: 5000 }, async (t) => {
    const child = spawn(
      process.execPath,
      ["-r", path.join(__dirname, "stream-shutdown.cjs"), "-e", "console.log('up'); setInterval(() => {}, 1000)"],
      { stdio: ["ignore", "pipe", "inherit"] },
    );
    t.after(() => child.kill("SIGKILL"));
    await new Promise((resolve) => child.stdout.once("data", resolve));

    const started = Date.now();
    const exited = new Promise((resolve) => child.once("exit", (c, s) => resolve([c, s])));
    child.kill(signal);
    assert.deepEqual(await exited, [code, null]);
    assert.ok(Date.now() - started < 1000, "it exited at once");
  });
}
