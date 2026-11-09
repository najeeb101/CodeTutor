# Deploying CodeTutor

Status: **Deploy Step 1 of 6.** The whole app runs in containers, on a laptop or a server, with
the same images. It is **not ready for strangers yet**; see section 5.

## 1. The containers

`compose.prod.yaml` starts five containers from three images (`deploy/`):

| Container | Image | What it does |
|---|---|---|
| `db` | `pgvector/pgvector:pg17` (pinned) | Postgres + pgvector. No port is published: only the other containers reach it |
| `migrate` | `codetutor-app` | Runs once: `alembic upgrade head`, then copies the problems in. The others wait for it to finish, so only one problem sync ever runs |
| `api` | `codetutor-app` | FastAPI on port 8000 inside the network (127.0.0.1:8010 on the machine) |
| `worker` | `codetutor-app` | Takes queued submissions and grades each one in a fresh `codetutor-sandbox` container |
| `web` | `codetutor-web` | Next.js on port 3000 inside (127.0.0.1:3200 on the machine); forwards `/api/*` to `api` |
| `tutor` | `codetutor-app` | Off by default (profile `tutor`) until Deploy Step 4 decides where the model runs |

`codetutor-sandbox` is not a running service. It is the pinned `python:3.12-slim` plus
`runner.py`, and the worker starts one container of it per submission, with the same locks as
before: no network, read-only, `nobody`, all capabilities dropped, memory, CPU and process limits.

**One image, four roles.** `codetutor-app` holds the Python code once. The compose file picks the
command (migrate, api, worker, tutor), so all four always run the same code version.

## 2. Run it on your machine

```bash
cp .env.prod.example .env.prod   # then fill in the two values (openssl rand -hex 24)
make prod-build                  # builds the 3 images (first time ~2.5 min)
make prod-up                     # starts everything and waits until it is healthy
make prod-e2e                    # 9 end-to-end checks over HTTP (no tutor yet)
make prod-down                   # stops it (the database volume is kept)
```

Open http://127.0.0.1:3200. `make prod-ps` shows the containers, and `make prod-logs` follows
their logs. Measured on the laptop (2026-11-09): build 2 min 34 s, start 26 s, first grading
3.6 s. Image sizes: app 421 MB, web 996 MB, sandbox 177 MB.

## 3. Design decisions

- **The runner lives in the grading image.** Locally, `DockerSandbox` bind-mounts `runner.py`
  from the package folder. A worker *inside* a container can't do that: the Docker daemon looks
  up bind-mount paths on the host's disk, where the worker's files don't exist. So the worker uses
  `codetutor-sandbox` (`SANDBOX_IMAGE`), and at start it checks that the image's runner is
  byte-identical to its own. A stale image is refused ("rebuild it: make prod-build"), because
  it would otherwise grade with an old runner without anyone noticing. Same Python, same runner,
  same options, so `GRADER_VERSION` did not change; a test grades fizzbuzz both ways and compares.
- **Pinned and multi-arch.** Every base image is pinned by digest and has amd64 and arm64
  builds. CI builds and runs the whole stack on both (`prod-images` job), because the planned
  server (Oracle Cloud Always Free) is ARM.
- **Least privilege.** The app containers run as uid 10001, the web as `node`, with read-only
  filesystems (only `/tmp` is writable). `.dockerignore` keeps every `.env*` file, `.git`, the
  virtual environment and the lab data out of the build, so a secret can never end up in an image.
- **Build-time vs run-time settings.** Next.js computes the `/api` rewrite when it builds, so the
  web image is built with `CODETUTOR_API_URL=http://api:8000`. Secrets are only read at run
  time from `.env.prod` (git-ignored, and checked by `scripts/check_secrets.py`).
- **Logs rotate** (3 × 10 MB per container), so they can't fill the server's disk.

## 4. The Docker socket (an honest trade-off)

The worker needs `/var/run/docker.sock` to start grading containers. **Whoever can use that
socket is as powerful as root on the machine.** That is true for any process that runs `docker`,
including `make worker` on a laptop. What keeps it acceptable:

- the worker's own code is ours; student code never sees the socket: it runs in the sandbox
  containers, with no network and no host files;
- the socket is mounted only into `worker`, never into `api`, `web` or `tutor`.

Better isolation is Deploy Step 3: gVisor (`runsc`) runs each grading container on its own
user-space kernel, so a kernel bug is much harder to reach.

## 5. Not safe for strangers yet

| Gap | Fixed in |
|---|---|
| Dev login: any `X-User-Id` works; the instructor token is one shared secret | Step 2 |
| The API's database user can read `problem_versions` (the hidden tests) | Step 2 |
| No request-size, per-IP or global limits | Step 2 |
| Grading containers share the host kernel | Step 3 |
| No tutor model on the server | Step 4 |
| No HTTPS, no server, no backups | Step 5 |

## 6. Known limits

- The web image is large (996 MB: `next` 203 MB, its platform build 93 MB, `monaco-editor`
  105 MB that only the browser needs). Next.js's `output: "standalone"` would shrink it a lot
  (docs/ideas.md).
- The tutor container is untested: on 2026-11-09 the laptop's Ollama was not running, and a
  container could not reach `host.docker.internal:11434`. Step 4 decides.
- `DOCKER_GID` is read from the host's socket by `make`. On Docker Desktop (this laptop) the
  socket's group inside containers matched the host (1001); check it again on the server.
