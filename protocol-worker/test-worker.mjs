import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import worker from "./worker.mjs";

const markdown = await readFile(new URL("./protocol.md", import.meta.url), "utf8");

async function request(path = "/", headers = {}, method = "GET") {
  return worker.fetch(new Request(`https://protocol.m8shift.ai${path}`, { method, headers }));
}

const agent = await request("/", { Accept: "text/markdown", "User-Agent": "curl/8.0" });
assert.equal(agent.status, 200);
assert.equal(agent.headers.get("Content-Type"), "text/markdown; charset=utf-8");
assert.equal(agent.headers.get("Cache-Control"), "public, max-age=3600");
assert.equal(await agent.text(), markdown);
assert.ok(agent.headers.get("ETag"));

const defaultResponse = await request("/", { "User-Agent": "curl/8.0" });
assert.equal(defaultResponse.headers.get("Content-Type"), "text/markdown; charset=utf-8");

const nonBrowserHtml = await request("/", { Accept: "text/html", "User-Agent": "curl/8.0" });
assert.equal(nonBrowserHtml.headers.get("Content-Type"), "text/markdown; charset=utf-8");

const browser = await request("/", {
  Accept: "text/html,application/xhtml+xml",
  "User-Agent": "Mozilla/5.0 Firefox/128.0",
});
assert.equal(browser.status, 200);
assert.equal(browser.headers.get("Content-Type"), "text/html; charset=utf-8");
assert.ok(browser.headers.get("Content-Security-Policy"));
const browserBody = await browser.text();
assert.match(browserBody, /<title>Agent Exchange Protocol<\/title>/);
assert.match(browserBody, /<meta name="description"/);
assert.match(browserBody, /<link rel="canonical" href="https:\/\/protocol\.m8shift\.ai\/">/);
assert.match(browserBody, /application\/ld\+json/);
assert.match(browserBody, /Maintain exactly one authoritative coordination surface/);

const markdownPath = await request("/AGENT-EXCHANGE-PROTOCOL.md", {
  Accept: "text/html",
  "User-Agent": "Mozilla/5.0 Firefox/128.0",
});
assert.equal(markdownPath.headers.get("Content-Type"), "text/markdown; charset=utf-8");
assert.equal(await markdownPath.text(), markdown);

const llms = await request("/llms.txt");
assert.equal(llms.headers.get("Content-Type"), "text/plain; charset=utf-8");
assert.match(await llms.text(), /^Agent Exchange Protocol\n/);

const notModified = await request("/", {
  Accept: "text/markdown",
  "If-None-Match": agent.headers.get("ETag"),
});
assert.equal(notModified.status, 304);
assert.equal(await notModified.text(), "");

const head = await request("/", { Accept: "text/markdown" }, "HEAD");
assert.equal(head.status, 200);
assert.equal(await head.text(), "");

const missing = await request("/missing");
assert.equal(missing.status, 404);

console.log("worker contract: OK");
