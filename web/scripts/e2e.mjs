// Browser end-to-end check of the running web UI (make web-e2e). Needs the three servers:
// `make worker`, `make api`, `make web`. No packages: Chrome is remote-controlled through its
// DevTools protocol over Node 24's built-in WebSocket.
//
// It starts its own headless Chrome with a throw-away profile (deleted at the end) and the
// debugging port on localhost. In WSL it uses the Windows Chrome by default; CHROME=/path picks
// another one. WEB_URL (default http://localhost:3100) and E2E_DEBUG_PORT (9333) override the
// addresses. On a failure, a screenshot goes to web/.e2e/ and the exit code is 1.
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WEB = process.env.WEB_URL ?? "http://localhost:3100";
const PORT = Number(process.env.E2E_DEBUG_PORT ?? 9333);
const DEBUG = `http://127.0.0.1:${PORT}`;
const PROBLEM = "cs1.loops.fizzbuzz";
const FOLDER = new URL("../../problems/cs1/03_loops/fizzbuzz/", import.meta.url);
const SOLUTION = readFileSync(new URL("solution.py", FOLDER), "utf8");
const BUGGY = readFileSync(new URL("buggy/checks_fizz_first.py", FOLDER), "utf8");
const USER = `e2e-ui-${Date.now()}`;
const ARTIFACTS = new URL("../.e2e/", import.meta.url);
const WINDOWS_CHROME = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class CheckFailed extends Error {}

function expect(condition, message) {
  if (!condition) throw new CheckFailed(message);
}

async function waitFor(check, what, timeoutMs = 30_000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const value = await check();
    if (value) return value;
    await sleep(200);
  }
  throw new CheckFailed(`timed out after ${timeoutMs / 1000} s waiting for ${what}`);
}

// --- Chrome: find it, give it a throw-away profile, start it, stop it ---

function isWsl() {
  return existsSync("/proc/version") && readFileSync("/proc/version", "utf8").toLowerCase().includes("microsoft");
}

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  if (isWsl() && existsSync(WINDOWS_CHROME)) return WINDOWS_CHROME;
  throw new Error("no Chrome found: set CHROME=/path/to/chrome (or chromium)");
}

// A Windows Chrome needs a Windows folder; we create and delete it through its WSL path.
function makeProfile(chrome) {
  if (!chrome.endsWith(".exe")) {
    const dir = mkdtempSync(join(tmpdir(), "codetutor-e2e-"));
    return { dir, chromeDir: dir };
  }
  const windowsTemp = execFileSync("cmd.exe", ["/c", "echo %TEMP%"], { cwd: "/mnt/c" }).toString().trim();
  const linuxTemp = execFileSync("wslpath", ["-u", windowsTemp]).toString().trim();
  const dir = mkdtempSync(join(linuxTemp, "codetutor-e2e-"));
  return { dir, chromeDir: execFileSync("wslpath", ["-w", dir]).toString().trim() };
}

// On WSL a closed port times out instead of refusing (mirrored networking), so each probe gets
// a short limit. Without it, the probes before start and after close took ~36 s (measured).
async function debugPortAnswers() {
  const answer = await fetch(`${DEBUG}/json/version`, { signal: AbortSignal.timeout(1000) }).catch(() => null);
  return answer?.ok ?? false;
}

async function startChrome() {
  if (await debugPortAnswers()) {
    throw new Error(`port ${PORT} already answers (a leftover Chrome?): close it or set E2E_DEBUG_PORT`);
  }
  const chrome = findChrome();
  const profile = makeProfile(chrome);
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${profile.chromeDir}`,
    `--remote-debugging-port=${PORT}`,
    "about:blank",
  ];
  const child = spawn(chrome, args, { stdio: "ignore" });
  await waitFor(debugPortAnswers, "Chrome's debugging port", 20_000);
  return { child, profile };
}

async function stopChrome({ child, profile }) {
  try {
    const { webSocketDebuggerUrl } = await (await fetch(`${DEBUG}/json/version`)).json();
    const socket = new WebSocket(webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = reject;
    });
    socket.send(JSON.stringify({ id: 1, method: "Browser.close" }));
  } catch {
    child.kill();
  }
  await waitFor(async () => !(await debugPortAnswers()), "Chrome to exit", 10_000).catch(() => child.kill());
  for (let attempt = 0; attempt < 10; attempt++) {
    deleteProfile(profile);
    if (!existsSync(profile.dir)) return;
    await sleep(500); // Chrome's helper processes may hold files for a moment
  }
  console.warn(`could not delete the temporary profile ${profile.dir}`);
}

// A Windows profile is deleted by Windows itself: through WSL's file bridge, deleting its
// hundreds of small files took ~12 s (measured), with `rmdir` well under a second.
function deleteProfile(profile) {
  try {
    if (profile.chromeDir !== profile.dir) {
      execFileSync("cmd.exe", ["/c", "rmdir", "/s", "/q", profile.chromeDir], { cwd: "/mnt/c", stdio: "ignore" });
    } else {
      rmSync(profile.dir, { recursive: true, force: true });
    }
  } catch {
    // checked by the caller (the folder still exists)
  }
}

// --- One page, remote-controlled ---

async function openPage(url) {
  const target = await (await fetch(`${DEBUG}/json/new?${url}`, { method: "PUT" })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let nextId = 1;
  const pending = new Map();
  const consoleErrors = [];
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.exception?.description ?? "exception");
    } else if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(" "));
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const id = nextId++;
      pending.set(id, resolve);
      socket.send(JSON.stringify({ id, method, params }));
    });
  // Run JavaScript in the page and return its (JSON-able) value.
  const js = async (expression) => {
    const reply = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (reply.result?.exceptionDetails) throw new CheckFailed(`page script failed: ${expression}`);
    return reply.result?.result?.value;
  };
  const screenshot = async (name) => {
    const reply = await send("Page.captureScreenshot", { format: "png" });
    mkdirSync(ARTIFACTS, { recursive: true });
    const file = new URL(`${name}.png`, ARTIFACTS);
    writeFileSync(file, Buffer.from(reply.result.data, "base64"));
    return file.pathname;
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false });
  return { send, js, screenshot, consoleErrors };
}

// --- The steps ---

const RESULT = "document.querySelector('.result:not(.pending) h3')?.textContent";

async function submitAndWait(page, code) {
  await page.js(`monaco.editor.getModels()[0].setValue(${JSON.stringify(code)})`);
  await page.js("document.querySelector('button.primary').click()");
  // A successful submit clears the old result, then shows "Grading…" until the new one is done.
  await waitFor(() => page.js("!document.querySelector('.result:not(.pending)')"), "the submit to be accepted", 10_000);
  return waitFor(() => page.js(RESULT), "the result (is `make worker` running?)", 60_000);
}

function steps(page) {
  return [
    ["page hydrates: Monaco editor and login form", async () => {
      await waitFor(() => page.js("!!document.querySelector('.monaco-editor') && !!document.querySelector('.login input')"), "the editor and the login form");
      return "ok";
    }],
    ["log in through the form", async () => {
      await page.js(`(() => {
        const input = document.querySelector('.login input');
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(USER)});
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector('.login button[type=submit]').click();
      })()`);
      await waitFor(() => page.js(`document.querySelector('.login')?.textContent.includes(${JSON.stringify(USER)})`), "the logged-in header");
      return USER;
    }],
    ["the solution is accepted", async () => {
      const heading = await submitAndWait(page, SOLUTION);
      const match = /^Accepted: (\d+) of (\d+) tests passed$/.exec(heading);
      expect(match && match[1] === match[2], `got "${heading}"`);
      return heading;
    }],
    ["a buggy solution fails, hidden tests show no details", async () => {
      const heading = await submitAndWait(page, BUGGY);
      expect(heading.startsWith("Wrong answer"), `got "${heading}"`);
      const rows = await page.js("[...document.querySelectorAll('.tests tbody tr')].map((tr) => [...tr.cells].map((td) => td.textContent))");
      const hiddenFailed = rows.filter(([test, status]) => test === "hidden test" && !status.includes("passed"));
      expect(hiddenFailed.length > 0, "no failed hidden test shown");
      expect(hiddenFailed.every(([, , details]) => details === ""), `hidden test details shown: ${JSON.stringify(hiddenFailed)}`);
      expect(await page.js("document.body.textContent.includes('A hidden test failed')"), "no hidden-test hint");
      return `${heading}; ${hiddenFailed.length} hidden failures without details`;
    }],
    ["fast submits hit the 'waiting' limit", async () => {
      for (let click = 1; click <= 6; click++) {
        await waitFor(() => page.js("!document.querySelector('button.primary').disabled"), "the submit button");
        await page.js("document.querySelector('button.primary').click()");
        await sleep(100);
        await waitFor(() => page.js("!document.querySelector('button.primary').disabled"), "the submit request");
        const message = await page.js("document.querySelector('[role=alert]')?.textContent ?? ''");
        if (message.includes("waiting to be graded")) return `after ${click} clicks: "${message}"`;
      }
      throw new CheckFailed("no 'waiting to be graded' message after 6 fast submits");
    }],
    ["reload keeps the draft and the login", async () => {
      await page.send("Page.reload");
      await sleep(500);
      await waitFor(() => page.js("!!window.monaco && monaco.editor.getModels().length > 0 && !!document.querySelector('.login button')"), "the page after reload");
      await sleep(300); // the draft is read right after the editor mounts
      expect((await page.js("monaco.editor.getModels()[0].getValue()")) === BUGGY, "the draft was not kept");
      expect(await page.js(`document.querySelector('.login').textContent.includes(${JSON.stringify(USER)})`), "logged out by the reload");
      const history = await waitFor(() => page.js("document.querySelectorAll('.history li').length"), "the submission list");
      return `draft kept, ${history} submissions listed`;
    }],
    ["log out", async () => {
      await page.js("[...document.querySelectorAll('.login button')].find((b) => b.textContent === 'Log out').click()");
      await waitFor(() => page.js("!!document.querySelector('.login input')"), "the login form");
      expect(await page.js("document.querySelectorAll('.history li').length === 0"), "the old user's submissions are still shown");
      return "login form back, submissions hidden";
    }],
    ["no errors in the browser console", async () => {
      expect(page.consoleErrors.length === 0, JSON.stringify(page.consoleErrors));
      return "none";
    }],
  ];
}

async function main() {
  const chrome = await startChrome();
  let failed = false;
  try {
    const page = await openPage(`${WEB}/problems/${PROBLEM}`);
    for (const [name, run] of steps(page)) {
      const started = Date.now();
      try {
        const detail = await run();
        console.log(`✅ ${name.padEnd(52)} ${((Date.now() - started) / 1000).toFixed(1).padStart(5)} s  ${detail}`);
      } catch (error) {
        const file = await page.screenshot("failure").catch(() => null);
        console.log(`❌ ${name.padEnd(52)} ${((Date.now() - started) / 1000).toFixed(1).padStart(5)} s  ${error.message}`);
        if (file) console.log(`   screenshot: ${file}`);
        failed = true;
        break;
      }
    }
  } finally {
    await stopChrome(chrome);
  }
  console.log(failed ? "Stopped at the first failed check." : "All browser checks passed.");
  return failed ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`❌ ${error.message}`);
    process.exit(1);
  },
);
