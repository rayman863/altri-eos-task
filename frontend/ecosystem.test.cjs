// node --test ecosystem.test.cjs : the PM2 cluster config (layer L2) reads WEB_INSTANCES
// strictly and preloads the same modules as the plain runner.
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");

const CONFIG = require.resolve("./ecosystem.config.cjs");

function load(webInstances) {
  delete require.cache[CONFIG];
  if (webInstances === undefined) delete process.env.WEB_INSTANCES;
  else process.env.WEB_INSTANCES = webInstances;
  return require(CONFIG).apps[0];
}

test("two cluster workers by default, or WEB_INSTANCES", () => {
  assert.equal(load(undefined).instances, 2);
  assert.equal(load("").instances, 2);
  assert.equal(load("3").instances, 3);
  assert.equal(load("max").instances, "max");
  assert.equal(load(undefined).exec_mode, "cluster");
});

test("a bad WEB_INSTANCES stops the start instead of guessing", () => {
  for (const bad of ["0", "-1", "two", "1.5", " 2"]) {
    assert.throws(() => load(bad), /WEB_INSTANCES must be a positive whole number/);
  }
});

test("workers run Next's server with both preloads, like start.sh's plain runner", () => {
  const app = load(undefined);
  assert.equal(app.script, path.join(__dirname, "server.js"));
  assert.deepEqual(app.node_args, [
    "-r",
    path.join(__dirname, "edge-headers.cjs"),
    "-r",
    path.join(__dirname, "stream-shutdown.cjs"),
  ]);
});
