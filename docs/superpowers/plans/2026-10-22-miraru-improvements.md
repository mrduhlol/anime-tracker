# Miraru Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the agreed improvement set (code-health, new docs, Docker, Expo mobile write support, cache-invalidation audit, router split of main.py, Simkl sync) so the fork can be proposed upstream as clean, reviewed PR-sized branches.

**Architecture:** Python 3.10+ FastAPI + SQLite backend with vanilla-JS frontend; frontend assets live in `static/`, pages in `templates/`. Tasks are grouped so that Phase A tasks never touch `main.py` or `static/sw.js` (except Task 3, which owns `sw.js`), enabling parallel subagent dispatch. Phase B tasks (router split, Simkl) are sequential because they edit `main.py`.

**Tech Stack:** Python 3.13 (local), FastAPI 0.125 + Pydantic 1.10.26 (pinned), pytest + httpx, ruff, Docker, Expo/React Native 0.79 + NativeWind.

**Spec:** Conversation with user ("do all those") — improvement list from repo audit. Baseline verified: `python -m pytest tests/ -q` → 505 passed; `python -m ruff check .` → clean.

## Global Constraints

- **Python ≤ 3.13.** FastAPI 0.125 forces the pydantic-v2 shim on Python ≥ 3.14 and `tests/` cannot even be collected. Local: `mise use python@3.13.11`, deps via `pip install -r requirements.txt -r requirements-dev.txt`.
- **Pydantic 1 pinned** at `1.10.26` pure-python wheel: use `pydantic.validator` only via the existing try/except `field_validator` shims in `main.py`; never import pydantic-v2 APIs.
- **Ruff:** line-length 110, config in `pyproject.toml`. Gate: `python -m ruff check .` clean.
- **Test gate:** `python -m pytest tests/ -q` → all pass (505+ at baseline). New code needs tests following the existing `tests/test_*.py` style (httpx + FastAPI TestClient patterns already present).
- **Comments and docstrings in Spanish** (codebase convention); UI strings go through `i18n.py` / `i18n_ui.py` (4 languages: es/en/fr/de).
- **No new runtime dependencies** unless a task's tests prove they're needed — PyInstaller size and Windows Smart App Control (unsigned-DLL) constraints are project-critical (`requirements.txt` comments explain why).
- **Windows-first desktop app:** server binds `127.0.0.1` by default; mobile/LAN mode is opt-in with PIN and has a dedicated security test (`tests/test_seguridad_lan.py`) that must stay green.
- Commits: conventional prefixes (`feat:`, `refactor:`, `docs:`, `test:`), imperative English subject line.

## Review Focus

1. **Service Worker cache staleness** — after moving CSS/JS out of HTML into `static/`, an old cached page would load before the new asset URL; expect the SW cache manifest/version to be updated in the same commit. Test: `tests/test_sw_cache_version.py::test_sw_lists_extracted_assets` pins every `static/` asset referenced from `templates/` into `sw.js`'s cache list. (Task 4 owner.)
2. **Cache invalidation on every mutating endpoint** — `database.py` caches `listar_animes()` in `_lista_cache`; a mutation that bypasses `db.` mutation helpers serves stale data indefinitely. Expected: every mutating API route either calls a `db.` helper that seeds `_invalidar_cache()` or the route calls it explicitly. Test: the audit task adds a parametrized test hitting each mutating endpoint against a temp DB and asserting `_lista_cache` was invalidated. (Task 6 owner.)
3. **Windows firewall / bind address in Docker** — Docker images traditionally publish the LAN port; the app was never designed as a network server. Expected: image default binds `0.0.0.0` inside the container with documented PIN-for-LAN warning; `uvicorn --host` flag wired through an env var only. No test daemonizes Docker in CI; coverage is docs-only + `docker build` success note. (Task 5 owner.)
4. **Expo writes silently lost when host PIN disabled** — `/api/mobile/*` endpoints 401/403 when mobile access is off; the Expo UI must surface that state instead of clearing form fields. Test: `mobile-expo/lib/api.test.ts` (or typecheck + manual note if no RN test runner is configured — check `mobile-expo/package.json`; do NOT add a new test dependency for this). (Task 7 owner.)
5. **`main.py` router split must be behavior-preserving** — the file wires singletons (rate limiter, mobile token, background threads, lifespan startup at module import). Expected: identical app behavior, same route paths, same module-level side effects order; no route renamed. Test: the full existing suite — plus `tests/test_unify.py` and `tests/test_test_sin_servidor.py` — must pass unchanged, and `main.app` must expose the same route set as before (pinned by a new `tests/test_route_set.py`). (Task 8 owner.)

---

## Phase A — independent tasks (parallel subagents)

### Task 1: CONTRIBUTING.md + .editorconfig

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `.editorconfig`

**Interfaces:**
- Consumes: nothing.
- Produces: docs only; no code interfaces.

- [ ] **Step 1:** Create `CONTRIBUTING.md`: bilingual (EN + ES sections) concise guide — dev setup (`mise use python@3.13.11`, `pip install -r requirements-dev.txt`), run app (`python launcher.py`), run tests (`python -m pytest tests/ -q`), lint (`python -m ruff check .`), code conventions (Spanish comments, ruff 110, Pydantic 1 shim pattern, no new unsigned-DLL deps), PR checklist. Reference licensing MIT.
- [ ] **Step 2:** Create `.editorconfig` (utf-8, lf, 4-space Python, 2-space JS/CSS, trailing whitespace trim, final newline).
- [ ] **Step 3:** Verify: `python -m ruff check .` passes (docs are lint-neutral), suite still passes.
- [ ] **Step 4:** Commit `docs: add contributing guide and editorconfig`.

### Task 2: Extract inline CSS from `templates/index.html` into `static/`

**Files:**
- Modify: `templates/index.html` (remove `<style>` blocks)
- Create: `static/index_page.css` (one or more files, by section)
- Test: `tests/test_extract_assets.py` (new, shared with Task 3 — Task 3 creates the sw.js manifest test; Task 2 only adds collection)

**Interfaces:**
- Consumes: existing FastAPI static mount `/static` (already mounted in `main.py:176`).
- Produces: `templates/index.html` references `/static/index_page.css`; Task 3 relies on `static/` same pattern; **Task 2 must NOT edit `static/sw.js`** (Task 3 owns it).
- Constraint: extraction must be purely visual-neutral; keep selector text byte-identical. If `<style>` blocks are many, split into `static/css/*.css` per block and link each; keep original order (cascade preserved). Check `static/sw.js` but only report findings — no edits.

- [ ] **Step 1:** Write test asserting `templates/index.html` contains no `<style>` tag and declares `<link rel="stylesheet" href="/static/…">` for each extracted file.
- [ ] **Step 2:** Run test → FAIL (styles still inline).
- [ ] **Step 3:** Move every `<style>…</style>` body byte-identically into new files under `static/`, replace with `<link>` tags in same position.
- [ ] **Step 4:** Run test → PASS. Manually open `http://127.0.0.1:8765` after running `python main.py` briefly (or just diff-check the served page via TestClient `GET /`) to confirm the page still renders and CSS requests return 200.
- [ ] **Step 5:** `python -m pytest tests/ -q` full suite → PASS. Commit `refactor: extract index page styles into static assets`.

### Task 3: Extract inline JS/CSS from `templates/stats.html` + update `static/sw.js` cache manifest

**Files:**
- Modify: `templates/stats.html`
- Create: `static/stats_page.js` (+ `static/stats_page.css` if styles present)
- Modify: `static/sw.js` (add extracted assets; bump cache version constant)
- Test: `tests/test_sw_cache_version.py` (new)

**Interfaces:**
- Consumes: Task 2's pattern; static mount `/static`.
- Produces: the ONLY task allowed to edit `static/sw.js`. Also adds the shared TC pinning that every `static/` file referenced by any template appears in `sw.js` `CACHE_NAME` precache list.

- [ ] **Step 1:** Read `static/sw.js`; note cache-name/version string and precache list format.
- [ ] **Step 2:** Write `tests/test_sw_cache_version.py`: (a) `templates/index.html` and `templates/stats.html` contain no `<style>` and no inline `<script>` larger than a small bootstrap (only `templates/stats.html` still has inline JS at this point — the test asserts the two files reference `/static/stats_page.js`); (b) every static asset referenced from those two templates is listed in `sw.js` precache list (parse with regex in the test).
- [ ] **Step 3:** Run test → FAIL.
- [ ] **Step 4:** Move inline `<script>`/`<style>` from `stats.html` to `static/stats_page.{js,css}` byte-identically; add `<script src>`/`<link>` in the same spot. Update `sw.js` (add assets, bump version). Mind the i18n mechanism — if inline JS uses server-injected template variables (`{{ … }}` jinja-ish or manual), keep the bootstrap that wires variables into a `window.*` global inline and move the rest.
- [ ] **Step 5:** Run test → PASS; full suite → PASS. Commit `refactor: extract stats page assets and refresh sw cache manifest`.

### Task 4: Dockerfile + self-host docs

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docs/self-host.md`
- Modify: `README.md` (short section linking `docs/self-host.md`)

**Interfaces:**
- Consumes: `main.py` starts uvicorn on `PORT` env already? — VERIFY the port/host env vars actually used by `main.py`'s `__main__` block and `launcher.py` (`ANIME_APP_DIR`, `ANIME_DB_PATH` seen in `database.py`). Use exactly those names.
- Produces: image runs `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8765}`; volume paths documented for `/data/db`.

- [ ] **Step 1:** Verify how `main.py` resolves host/port and make the Dockerfile declare matching `ENV` defaults (do not change `main.py` behavior; if it hardcodes 127.0.0.1, pass extra uvicorn args in the image CMD instead of editing host logic).
- [ ] **Step 2:** Write `Dockerfile`: python:3.13-slim, `pip install -r requirements.txt` (no dev deps — no test/lint/build tools in the image), copy source, non-root user, `VOLUME` or documented `-v`, `CMD` uvicorn. `.dockerignore`: `.git`, `tests/*`, `mobile-expo/*`, `node_modules`, `dist/`, `build/`, `*.exe`.
- [ ] **Step 3:** Write `docs/self-host.md`: run instructions (`docker run -p 8765:8765 -v data:/data …`), management (updates, SQL backup), and a clear warning that exposing beyond localhost needs the PIN + reverse-proxy TLS at minimum (mirror the LAN-PIN posture of `docs: mobile access`).
- [ ] **Step 4:** README short section under Instalación linking to the doc (English one-liner + Spanish one-liner).
- [ ] **Step 5:** `docker build -t miraru .` (fails gracefully if no docker available → document manual verification steps; minimum check: run `python -c "import uvicorn"` in a buildless sanity path). Verify suite passes. Commit `feat: docker image for self-hosting`.

### Task 5: mobile-expo write support (frontend only — backend endpoints already exist)

**Files:**
- Modify: `mobile-expo/lib/api.ts` — add `patchAnime(nombre, patch)` and `plusOne(nombre)` mirroring `PATCH /api/mobile/animes/{nombre:path}` and `POST /api/mobile/animes/{nombre:path}/plus1`; types follow existing `Anime`.
- Modify: `mobile-expo/app/(tabs)/index.tsx` — wire buttons (status picker, +1 episode, score entry) calling the new API fns; handle 401/PIN-disabled state with an alert + "settings" hint, never silent data loss.
- Modify: `mobile-expo/app/(tabs)/ajustes.tsx` only if a "host connected?" indicator needs it.
- Test: JS-level check `npx tsc --noEmit` from `mobile-expo/` (already scripted as `typecheck`) — no new test deps.

**Interfaces:**
- Consumes: backend endpoints verified above; existing `getHost/getToken` helpers and `Anime` type in `lib/api.ts`.
- Produces: exported `patchAnime(nombre: string, cambios: Partial<Anime & { estado_usuario?: string }>): Promise<Anime>` and `plusOne(nombre: string): Promise<{ ok: true }>` (names may follow the module's existing Spanish/English naming mix — match the file).

- [ ] **Step 1:** Read all three tsx tabs and api.ts fully; keep the UI idioms of the file (component style, styling approach).
- [ ] **Step 2:** Implement `api.ts` functions with the same fetch/throw shape as existing ones (include token header exactly as the other calls do).
- [ ] **Step 3:** Wire the index tab: +1 button (calls plusOne, optimistic UI with rollback on error), state change via status picker, score via simple press-step or input as file idiom dictates; on 401 show connectivity/PIN alert.
- [ ] **Step 4:** Run `npm install --no-audit --no-fund` is heavy — PREFER `npx --yes tsc --noEmit` against the project's `tsconfig.json` typecheck only; if RN deps missing make typecheck degrade, document the manual check instead of installing full Expo toolchain. Do not commit `node_modules`.
- [ ] **Step 5:** Commit `feat(mobile): episode progress and status editing in Expo app`.

### Task 6: Cache-invalidation audit with pinned test

**Files:**
- Test: `tests/test_cache_invalidez.py` (new)
- Modify (only if audit finds gaps): `main.py` or `database.py` — **keep the diff minimal**; large edits would collide with Task 8. If gaps require touching many routes, report instead of refactor.

**Interfaces:**
- Consumes: `database._invalidar_cache`, `database._lista_cache`, db helpers; the app via TestClient.
- Produces: one test module pinning that every mutating endpoint invalidates `_lista_cache`.

- [ ] **Step 1:** Grep `database.py` for every function that calls `_invalidar_cache` and for mutating functions (alta/modificar/borrar/…); list which `main.py` routes build mutations NOT through those helpers (raw `_consultar`/`_ejecutar` writes).
- [ ] **Step 2:** Write `tests/test_cache_invalidez.py`: parametrize over the mutating endpoints found in step 1; client fixture with a temp DB (copy the pattern from `tests/test_database.py`); spot the cache before/after — pre-populate by reading a listing endpoint once (warms `_lista_cache`), mutate, then assert the next listing reflects the change (functional assertion rather than spying internals — resilient to refactor in Task 8).
- [ ] **Step 3:** Run new test → if any endpoint is stale-after-listing, fix the minimal route/helper to route mutations through db helpers (or call `_invalidar_cache`).
- [ ] **Step 4:** Full suite → PASS. Commit `test: pin cache invalidation across mutating endpoints` (plus `fix:` commit if gaps were fixed).

## Phase B — sequential tasks (after Phase A merges into the branch)

### Task 7: Split `main.py` into API routers (behavior-preserving)

**Files:**
- Create: `routes/` package (`routes/auth_mobile.py`, `routes/sync.py`, `routes/search.py`, …) — exact split decided during execution by route-cluster mapping below.
- Modify: `main.py` (keep app creation, middleware, lifespan, module-level singletons, `if __name__ == "__main__"`; include routers with the original route order preserved as much as practical.)
- Test: `tests/test_route_set.py` (new)

**Interfaces:**
- Consumes: module singletons currently in `main.py` (rate limiter, mobile PIN/token, `trabajos` worker) — they stay importable from `main` to avoid import cycles: re-export what moved code needs, or push helpers down to `core.py`/new module and import from there, following the existing `core.py` precedent.
- Produces: `main.app` route set identical to pre-refactor (paths, methods, response classes). `main` keeps top-level names other tests import (check which tests import attributes from `main` before moving anything — grep `from main import|from main:` and `import main`).

- [ ] **Step 1:** Capture the baseline route table: TestClient `.routes` sorted `(path, method)`; write `tests/test_route_set.py` asserting equality against a hardcoded list dumped from the current commit (generate it programmatically in-place).
- [ ] **Step 2:** Run test → PASS pre-refactor (sanity).
- [ ] **Step 3:** Split routes into clusters by domain: search/fuentes, animes CRUD, móvil/auth, sync (anilist/animeav1/sheets), notificaciones/push/email, estadísticas/gamificación/import-export, pginas estáticas. Move handler code verbatim (one business-logic-touching exception per step is forbidden—this task is mechanical only). Routers use `APIRouter()`, included via `app.include_router(...)`. Watch for `@app.on_event`/startup code and decorators with `include_in_schema=False` page routes — keep those in `main.py`.
- [ ] **Step 4:** `python -m pytest tests/ -q` → PASS, including `test_route_set.py`. `python -m ruff check .` → clean.
- [ ] **Step 5:** Commit `refactor: split main into API routers (behavior-preserving)`.

### Task 8: AniList replay export endpoint

(Simkl full sync needs upstream-provided OAuth credentials the fork cannot ship and cannot test; a token-config-based Simkl sync would be untestable and half-mock. Honest swap approved in conversation: implement the export as a pure, offline-testable builder that emits real AniList `SaveMediaListEntry` mutation payloads a user replays with their own token. Upstream can later extend it into true 2-way sync with credentials.)

**Files:**
- Create: `anilist_export.py`
- Modify: `main.py` (one route, after Task 7 lives in `routes/`)
- Test: `tests/test_export_anilist.py`

**Interfaces:**
- Consumes: `database.listar_animes()` slim dict shape; export/import route cluster from Task 7.
- Produces: `anilist_export.build_mutation(lista: list[dict], token_user_id: int) -> list[dict]` — pure function returning ready-to-send GraphQL mutation objects (must be offline-testable; HTTP replay documented, not implemented).

- [ ] **Step 1:** Write `tests/test_export_anilist.py`: given fixture animes with `anilist_id`, `estado_usuario` mapped to AniList status enums (pendiente→PLANNING, viendo→CURRENT, completado→COMPLETED, en pausa→PAUSED, abandonado→DROPPED), episodios_vistos→progress, puntuación rounded to available 100-point scale, output contains required fields; roundtrip uses offline assertion only.
- [ ] **Step 2:** Run → FAIL (module missing).
- [ ] **Step 3:** Implement pure builder + `POST /api/export/anilist` route returning the payload list; error 400 when no animes have `anilist_id`.
- [ ] **Step 4:** Tests → PASS; suite → PASS; ruff → clean. Commit `feat: AniList replay export endpoint`.

## Execution sequencing

1. Phase A tasks 1–6 in parallel subagents (no shared files; Task 3 owns sw.js).
2. Join → run full suite + ruff.
3. Phase B tasks 7 → 8 sequentially (both touch `main.py`).
4. Final: whole-branch review subagent, then the user decides PR packaging (likely separate upstream PRs per phase).
