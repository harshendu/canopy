# Canopy browser end-to-end tests (Selenium)

Browser-driven end-to-end specs that exercise the **real React app against a
real FastAPI backend** — the flows a human clicks through, asserted in a headless
Chrome via Selenium WebDriver. They complement (don't replace) the backend
`pytest` and frontend `vitest` suites, which test units in isolation.

These specs are written against the user-facing flows catalogued in
[`docs/USER_FLOWS.md`](../docs/USER_FLOWS.md); each test references the section it covers.

## Layout

```
e2e/
  conftest.py        driver/browser auto-detection + fixtures (base_url, driver, auth_driver)
  helpers.py         selectors (XPath on visible text), waits, login flow, API arrange-helpers
  pytest.ini         markers (smoke/auth/nav/projects/planning)
  requirements.txt   selenium + pytest
  run_e2e.sh         boots the full stack, runs the suite, tears it down
  tests/
    test_smoke.py        app shell boots (§A1)
    test_auth.py         login ok/failed, logout, route guard (§A1, §A2)
    test_navigation.py   sidebar routes to every page (§A,B,F,G,J,M)
    test_projects.py     create a project, open the tabbed cockpit (§B2, §B3)
    test_planning.py     add tasks, run CPM, tab rendering (§C1, §C3, §B3)
    test_demo_seed.py    load the demo dataset + browse it (§Z; opt-in, E2E_DEMO=1)
```

`.venv/`, `.drivers/`, and the throwaway `.e2e.db` are git-ignored — they're
local machine state, not source.

`run_e2e.sh` boots the stack with `DEMO_MODE=true`, so the demo seed/reset endpoints and the
offline-mocked connectors are available. `test_demo_seed.py` is **opt-in** (`E2E_DEMO=1`) because
it reseeds — wiping the data other specs rely on — so run it on its own:
`E2E_DEMO=1 e2e/run_e2e.sh tests/test_demo_seed.py`.

## Running

### One command (boots the stack for you)

```bash
e2e/run_e2e.sh                 # full suite
e2e/run_e2e.sh -m smoke        # just the smoke marker
e2e/run_e2e.sh tests/test_planning.py -v
```

`run_e2e.sh` starts the backend (sqlite, migrated, with a seeded admin) and the
Vite dev server, waits for both health checks, runs `pytest`, and kills both on
exit. Extra args pass straight through to pytest.

### Against an already-running stack

If you already have the app up (e.g. `docker compose up`, or backend on `:8000`
+ `npm run dev` on `:5173`):

```bash
cd e2e
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
CANOPY_BASE_URL=http://127.0.0.1:5173 ./.venv/bin/python -m pytest
```

## Configuration (env vars)

| Variable            | Default                          | Purpose                                        |
|---------------------|----------------------------------|------------------------------------------------|
| `CANOPY_BASE_URL`   | `http://127.0.0.1:5173`          | Front-door URL of the running app              |
| `CANOPY_EMAIL`      | `architect@example.com`          | Login used by the auth fixtures                |
| `CANOPY_PASSWORD`   | `canopy-dev-password`            | Password for that login                        |
| `E2E_HEADLESS`      | `1`                              | `0` to watch the browser run                   |
| `E2E_CHROME_BINARY` | auto-detected                    | Explicit Chrome/Chromium binary                |
| `E2E_CHROMEDRIVER`  | auto-detected / Selenium Manager | Explicit chromedriver path                     |

The login defaults match the backend's `FIRST_SUPERUSER_EMAIL/PASSWORD` seeding,
so the runner's seeded admin works out of the box. Point them at any other user
to test a different role.

## Browser & driver

`conftest.py` resolves a browser and driver so the suite runs unchanged across
environments:

1. **Chrome binary** — `E2E_CHROME_BINARY`, else a system Chrome/Chromium on
   `PATH`, else a Playwright-managed Chromium under `/opt/pw-browsers` or
   `~/.cache/ms-playwright`.
2. **chromedriver** — `E2E_CHROMEDRIVER`, else a repo-local `e2e/.drivers/chromedriver`,
   else Selenium Manager / `PATH`.

On a normal dev machine with Chrome installed, **nothing needs setting** —
Selenium Manager downloads the matching driver automatically.

In a headless/CI/cloud sandbox you must supply binaries whose **major versions
match**. For example, with a Playwright Chromium 141:

```bash
# one-time: fetch the matching chromedriver (major version must equal Chrome's)
VER=141.0.7390.37
curl -sL -o /tmp/cd.zip \
  "https://storage.googleapis.com/chrome-for-testing-public/$VER/linux64/chromedriver-linux64.zip"
mkdir -p e2e/.drivers && unzip -j /tmp/cd.zip '*/chromedriver' -d e2e/.drivers

export E2E_CHROME_BINARY=/opt/pw-browsers/chromium-1194/chrome-linux/chrome
export E2E_CHROMEDRIVER=$PWD/e2e/.drivers/chromedriver
```

> A `SessionNotCreatedException: This version of ChromeDriver only supports
> Chrome version N` means the driver and the browser disagree on major version —
> fetch the chromedriver whose major version equals your Chrome's.

## Conventions for new specs

- **Select by what the user sees.** The app has no `data-testid`s; helpers target
  placeholders, button/link/label text, and headings via XPath. Add selectors to
  `helpers.py`, not inline in tests, so a label rename is a one-line fix.
- **Arrange via the API, act/assert via the UI.** Use the `api_*` helpers
  (stdlib `urllib`) to set up preconditions fast, then drive and verify the real
  UI. Don't assert app behaviour through the API.
- **Isolate.** The `driver` fixture is a fresh browser per test (no shared
  cookies/localStorage); `auth_driver` is the same, already logged in. Create
  data with unique keys so reruns don't collide.
- **Wait, don't sleep.** Use the `wait_*` / `has_text` helpers (explicit waits),
  never `time.sleep`.
- Keep each spec tied to a `docs/USER_FLOWS.md` section in its docstring.
