# Web UI (Weeks 3-4)

Next.js 16 (App Router) + React 19 + Monaco editor, TypeScript 7. A student logs in by name,
picks a problem, writes code in the editor, submits, sees the result, and can ask the AI tutor
for a hint and rate it 👍/👎 (Week 4). The UI only talks to
the HTTP API ([docs/api.md](../docs/api.md)); it never touches the database or the grader.

## Run it
Four terminals, from the repo root (Node 24 through nvm):
```bash
make worker        # grades submissions in Docker
make tutor         # answers hint requests with the local model (needs Ollama)
make api           # the HTTP API on 127.0.0.1:8000 (start it after the workers)
make web           # this UI on http://localhost:3100 (installs npm packages the first time)
```
Port 3100, not Next's usual 3000: another dev server on this laptop already uses 3000.
`WEB_PORT=3200 make web` picks another port. `make web-check` type-checks and builds for
production. `make web-install` runs `npm ci` (exact versions from `package-lock.json`).

## Layout
| Path | What it is |
|---|---|
| `app/layout.tsx` | page frame: header with the login box, `UserProvider` |
| `app/page.tsx` | problem list, grouped by module (server component) |
| `app/problems/[id]/page.tsx` | problem text and visible tests (server), then `Workspace` |
| `app/error.tsx`, `app/not-found.tsx` | "is the API running?" and 404 pages |
| `components/Workspace.tsx` | editor, submit, polling for the result, my submissions (client) |
| `components/HintPanel.tsx` | ask the tutor (question, level 1 → 2 → last hint), the hints, 👍/👎 |
| `components/InlineCode.tsx` | text with `backticks` shown as code (descriptions, hints) |
| `components/CodeEditor.tsx` | Monaco: Python, 4-space tabs, loaded from our own server |
| `components/ResultView.tsx` | one result: status, test table, hidden tests without details |
| `components/LoginBox.tsx` | "Start as a guest" / Log out; the session is an HttpOnly cookie, the page asks `GET /api/me` who it is |
| `lib/api.ts` | `apiFetch` + `ApiError` (status, detail, Retry-After): the only API caller |
| `lib/poll.ts` | `pollUntilFinished`: the polling loop shared by submissions and hints |
| `lib/types.ts` | the API's answers as TypeScript types (written by hand) |
| `lib/editorStats.ts` | `EditorTracker`: counts typed and pasted characters for the editor summary sent with each submit |
| `app/instructor/page.tsx`, `app/instructor/students/[id]/page.tsx` | teacher dashboard: overview, students (sortable), problems; one student with marks and a risk score (sortable Risk column, Risk card; client components) |
| `components/instructor/` | `TokenGate` (teacher token box), `OverviewCards`, `StudentTable`, `ProblemTable`, `Bar` |
| `lib/instructorToken.tsx` | the teacher dev token (sessionStorage, not localStorage) and `useInstructorData` |
| `lib/user.tsx`, `lib/storage.ts` | the logged-in user (React context + localStorage) |
| `lib/description.ts` | turns a problem's hard-wrapped text into paragraphs, lists and code |
| `scripts/copy-monaco.mjs` | copies Monaco into `public/monaco` after `npm install` |

## How it works
- **Server vs client components.** The problem list and problem text are the same for every
  student, so they are rendered on the server (`force-dynamic`: asked from the API on every
  request, never at build time). Login, the editor, submit and results need the student, so
  they run in the browser (`"use client"`).
- **One origin.** The browser calls `/api/...` on this server, and `next.config.ts` forwards it
  to `127.0.0.1:8000`. So there's no CORS, and the API stays on 127.0.0.1. Server components
  call the API directly (`CODETUTOR_API_URL`, default `http://127.0.0.1:8000`).
- **Submit, then poll.** A submit answers 202 at once. `Workspace` then asks
  `GET /api/submissions/{id}` once per second; each request waits for the previous one. It
  stops when the job is `done` or `failed`, after 2 minutes, or when the page closes (a
  "generation" counter stops the old loop). Measured: about 2.3 s from click to result for
  fizzbuzz (≈1.4 s in the worker, plus up to 1 s of polling). Hints use the same loop
  (`lib/poll.ts`), with 150 s to wait (a model that must load first took up to 109 s).
- **Hints.** The hint is about the shown submission when the editor holds exactly its code,
  else about the editor's code (not graded yet). Levels go in order; the last hint asks for
  confirmation first. A hint request still waiting after a reload is followed again.
- **Values look like Python.** The page shows the API's `*_repr` fields (Python's own `repr`),
  never raw JSON values. JavaScript has one number type, so `JSON.parse("32.0")` gives `32`,
  and the student would see the wrong type (and `null` instead of `None`).
- **Errors.** 401 clears the page's user and asks you to start again. 409 says "reload the page". 429
  shows the API's message and the `Retry-After` seconds.
- **Drafts.** Your unsent code is kept per problem in localStorage. "Reset to starter code"
  clears it.
- **Editor summary (Week 5).** `EditorTracker` listens to Monaco (`onDidChangeModelContent`,
  `onDidPaste`) and each submit sends its summary (times, typed and pasted characters; no
  keystrokes; [docs/api.md](../docs/api.md) §1), then starts a new window. Typed = all inserted
  characters minus pasted ones, so the order of Monaco's two events doesn't matter. The
  `@monaco-editor/react` wrapper applies a new `value` prop (a restored draft, "Reset") as a
  normal edit, not a "flush" (read in its source), so `Workspace` announces its own
  replacements (`expectReplace`) and the tracker skips them. Auto-indent, auto-closed brackets
  and undo count as typing (an approximation). A line under the editor tells the student.

## Decisions
- **Monaco is served by us**, not loaded from `cdn.jsdelivr.net` (the default of
  `@monaco-editor/react`). That would be third-party code at runtime, with no integrity check,
  and no editor offline. `npm install` copies `node_modules/monaco-editor/min/vs` (25 MB,
  gitignored) to `public/monaco/vs`.
- **No telemetry:** `NEXT_TELEMETRY_DISABLED=1` in every npm script (Next.js sends usage data
  to Vercel by default).
- **`agentRules: false`:** `next dev` 16.3 writes `AGENTS.md` and `CLAUDE.md` (instructions
  for AI coding agents) into this folder by default. This repo's agent instructions are
  written by its author, so the option is off.
- **TypeScript 7:** `next build` runs the project's own `tsc` (TypeScript 7 has no JavaScript
  API).
- **Plain CSS** (`app/globals.css`, colour variables for light and dark mode). No Tailwind, no
  component library.

## Checked
- `make web-check`: type check + production build.
- `make web-e2e` (`scripts/e2e.mjs`, needs both workers, the API and this UI running): starts
  a headless Chrome with a throw-away profile and remote-controls it through the DevTools
  protocol (Node 24's built-in WebSocket, no packages). 9 checks: the page hydrates (Monaco and
  the login form), log in, fizzbuzz's solution → Accepted 10/10, a buggy file → 6/10 with the
  failed hidden tests shown without details, a level 1 hint about it + 👍, fast submits → the
  "3 waiting" message, reload keeps the draft, the login and the rated hint, log out (hints
  and submissions gone), no console errors. ~27 s. On a failure it saves
  `web/.e2e/failure.png` and exits 1. In WSL it uses the Windows Chrome; `CHROME=/path`,
  `WEB_URL` and `E2E_DEBUG_PORT` (9333) override the defaults.
- `make e2e` (repo root) checks the same chain over plain HTTP, including the pages' HTML.

## Limitations
- The browser check is hand-written (no test framework) and opt-in: it is not part of
  `make all`, because it needs the four servers, Ollama and Chrome.
- The problem list has no "solved" marks (it would need the student's submissions).
- `lib/types.ts` is written by hand and can drift from the API's pydantic models.
- Guests are anonymous: a lost cookie is a lost account (docs/api.md §2).
- `npm audit` reports 2 low-severity advisories: monaco-editor 0.57 bundles DOMPurify 3.4.15
  (an XSS that needs DOMPurify's `IN_PLACE` mode). Monaco never turns that mode on (checked in
  the bundle), so it is not reachable here. Since Monaco is prebuilt, an npm override wouldn't
  change the served code. Check again when Monaco updates DOMPurify.
