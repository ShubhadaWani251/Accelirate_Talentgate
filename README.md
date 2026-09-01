# TalentGate

Candidate evaluation platform for Accelirate's fresher hiring pipeline: administrators and
Staffing Users (TAs) configure hiring batches, bulk-upload candidates, validate and deduplicate
them, run duplicate/cooling-off checks against candidate history, send assessment invitations,
manage a shared question bank, and review results.

## Status

The TA/Admin portal (auth, batches, candidate upload & validation, question bank, user
management, dashboards, email notifications) is built and in active use against a shared Azure
Postgres instance.

The candidate-facing assessment flow behind the `/t/<token>` invitation link is now built too:
email verification, identity capture, webcam proctoring with violation handling, the timed
attempt itself, scoring, and the result and termination screens. The endpoints are in
`Backend/api/views/exam.py` and the screens in `Frontend/src/pages/exam/`.

## Architecture

Two independently deployable apps in one repo:

```
Accelirate_TalentGate/
├── Backend/    Django REST API
├── Frontend/   React + Vite single-page app
└── backups/    Local DB backup dumps (gitignored - never committed)
```

### Backend (`Backend/`)

Django project `config/`, single Django app `api/` organized by responsibility rather than
by domain — given the app's current size this is simpler to navigate than splitting into
several Django apps would be, and avoids the migration/ContentType risk that splitting an
app with a live shared database entails:

```
Backend/
├── config/                  Project settings, root urlconf
├── api/
│   ├── models/               One file per entity group (batch, candidate, question, users)
│   ├── serializers/           DRF serializers, same grouping as models/
│   ├── views/                 DRF views, same grouping again
│   ├── services/              Business logic - the layer views/ call into: duplicate
│   │                          checking, Excel parsing/validation, email rendering &
│   │                          sending (Graph/SendGrid), user provisioning, batch-status
│   │                          filtering, audit logging, access/visibility rules
│   ├── management/commands/   One-off/admin CLI tasks (password reset, question dedupe,
│   │                          Graph email smoke test)
│   ├── migrations/
│   ├── authentication.py      Custom JWT auth wiring
│   ├── permissions.py         Role-based permission classes (IsAdmin / IsAdminOrTA)
│   ├── pagination.py
│   ├── validators.py
│   └── urls.py
├── fixtures/                 Seed data (roles/permissions)
├── requirements.txt
└── manage.py
```

Why `services/` matters: views stay thin (parse the request, call a service, shape the
response); the service functions hold the actual rules (e.g. when a batch may send invites,
how a duplicate Aadhaar/email is detected, how a candidate row is validated column-by-column)
and are what get reused across multiple views/management commands. If you're looking for
*why* something behaves a certain way, it's almost always in `services/`, not `views/`.

### Frontend (`Frontend/`)

Already organized feature-first, not by generic type:

```
Frontend/src/
├── api/            One axios module per backend resource (batchApi.js, candidateApi.js, ...)
├── app/            Redux store setup
├── features/       Feature-owned components/logic: auth, batches, candidates, questions, users
├── pages/           Route-level screens, composing components from features/ + components/
├── components/
│   ├── common/      Genuinely shared UI (modals, pagination, password input, status filter)
│   └── layout/       App-wide chrome (nav)
├── routes/          Route table + role-based route protection
├── styles/          Single theme.css (design tokens as CSS custom properties, shared
│                    .btn/.card/.data-table/.pill component classes)
└── utils/           Small, genuinely-reusable helpers (date formatting, error extraction)
```

### Why some things are NOT split further

Two deliberate decisions worth knowing before "fixing" them:

- **The backend stays one Django app.** Splitting `api/` into separate apps per domain
  (candidates, batches, question_bank, ...) was considered and explicitly deferred: Django ties
  migration history, `db_table` bindings, and `ContentType` rows to the app label a model was
  created under, so moving models between apps against a live shared database needs careful,
  verified migration surgery - not a file move. The current `models/`/`serializers/`/`views/`/
  `services/` split already gives most of the organizational benefit without that risk.
- **`requirements.txt` is generated, not hand-edited.** Declare direct dependencies in
  `Backend/requirements.in`, then regenerate:
  `pip install -r requirements.in && pip freeze > requirements.txt`. The split exists because a
  flat freeze cannot distinguish "we asked for this" from "something pulled it in", and that had
  gone badly wrong: 17 packages were pinned that nothing imported (celery, django-celery-beat,
  django-axes, django-prometheus, drf-yasg, django-filter, django-oauth-toolkit,
  django-extensions, factory_boy, Faker, Werkzeug, django-environ, sendgrid, numpy, pandas,
  xlrd, prometheus_client) while `python-dotenv` - imported on the first line of
  `settings.py` - was **missing**, so a clean `pip install -r requirements.txt` produced an app
  that could not start. Removing the unused set took the tree from 78 packages to 37.

## Setup

### Backend

```bash
cd Backend
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env           # fill in real values - see below
python manage.py migrate
python manage.py runserver
```

**No accounts are seeded by the fixtures.** For a local login, load the roles and create the
development Administrator:

```bash
python manage.py loaddata fixtures/initial_roles.json
python manage.py seed_dev_admin      # prints the credential it created
```

`seed_dev_admin` **refuses to run against any database whose host is not local**, so it cannot be
aimed at staging even with staging's `DB_*` values in the environment. The fixed password is only
acceptable because that guard exists - it is in source control, so treat removing the guard as
publishing an Administrator password for whatever the command is pointed at. For any shared
environment use `create_admin_user`, which takes the password as an argument and has no default,
or `reset_user_password`, which prompts instead so the value stays out of shell history.

### Frontend

```bash
cd Frontend
npm install
cp .env.example .env           # only needed if the backend isn't on localhost:8000
npm run dev
```

## Environment variables

Never commit a real `.env` file - both are gitignored. `Backend/.env.example` and
`Frontend/.env.example` list every variable the code actually reads, with placeholder values
and a comment on what each one does. Highlights:

- **Database**: `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` - Postgres.
- **Email**: `EMAIL_BACKEND` selects Microsoft Graph (default) or SendGrid; Graph needs
  `GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`/`GRAPH_SENDER` from an Azure AD app
  registration with **application-level** (not delegated) `Mail.Send` permission.
- **`SECRET_KEY`**: the checked-in default is dev-only and insecure. Generate a real one for
  any environment where `DEBUG=False`; the app will refuse to start without one in that case.
- **`SUPPORT_EMAIL`**: printed in the candidate assessment-invitation email as the contact
  address for technical issues. Must be a real monitored mailbox, not the noreply address.
- **`QUESTION_EXPORT_API_KEY`**: enables `GET /api/integrations/questions/active/`, a
  service-to-service export of the active question bank (correct answers included) for another
  system to consume, authenticated via the `X-API-Key` header instead of staff login. Blank
  disables the route entirely (every request gets 401). Every successful call is written to
  `AuditLog` with `requires_review=True`. Generate a value with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"` and rotate by changing this and
  updating whatever system holds the old value.

## Development commands

| | Backend | Frontend |
|---|---|---|
| Run dev server | `python manage.py runserver` | `npm run dev` |
| Build for production | - | `npm run build` |
| Lint | - | `npm run lint` |
| Django system checks | `python manage.py check` | - |
| Apply migrations | `python manage.py migrate` | - |
| Seed a local admin login | `python manage.py seed_dev_admin` | - |
| Create a migration | `python manage.py makemigrations api` | - |
| Run tests | `python -m pytest` | - |
| Check for uncommitted model changes | `python manage.py makemigrations --check --dry-run` | - |
| Production readiness check | `python manage.py check --deploy` | - |

### Scheduled jobs (required in any real deployment)

Three commands have to run on a timer. None is optional: without them, abandoned exam attempts
sit `in_progress` forever, unfinalized draft batches are never cleaned up, and **invitation
emails are never sent at all**.

There is no Celery/broker-based task queue - `process_email_queue` is a DB-backed one instead:
creating an Invitation (sending an invite, or re-sending one) only sets `email_status=QUEUED` on
the row; nothing sends it inline from the request that created it. `process_email_queue` is the
worker that drains that queue, run on whatever scheduler the host already provides (cron,
Windows Task Scheduler, the `scheduler` service in `docker-compose.yml`, or - on this App
Service, which has none of those - background loops in `Backend/startup.sh`).
See **Deployment** below for ready-made configurations.

| Command | Suggested interval | What it does |
|---|---|---|
| `python manage.py finalize_expired_attempts` | every 5-15 min | Finalizes exam attempts still `in_progress` past their deadline, and ones whose candidate never started before the invitation link expired. |
| `python manage.py process_email_queue` | every 1 min | Sends every queued invitation email - the only thing that does. Not a backup job like the other one; a candidate is waiting on this for their assessment link. Paced by `INVITE_SEND_DELAY_SECONDS` between sends, and stops auto-retrying a row past `INVITE_MAX_RETRY_ATTEMPTS` failures (`--include-failed` opts a run into retrying failures at all; `--ignore-retry-limit` overrides the cap for a deliberate one-off push). Skips rows whose link is already opened or expired. |

Both are safe to run more often than suggested - each is idempotent and does nothing when there
is nothing to process. `process_email_queue` specifically should not run LESS often than every
minute or two - unlike the other, nothing else stands in for it if it lags.

Draft batches are **not** auto-deleted - there used to be a 24-hour expiry job
(`delete_expired_draft_batches`); it was removed. A Draft now sits until a TA/admin deletes it
explicitly from the Drafts list in the UI (`services/draft_expiry.delete_draft_batch`).

## Testing

```bash
cd Backend && python -m pytest
```

212 tests, a few seconds. `pytest.ini` and `Backend/api/tests/` hold the suite; it covers
the invariants that are silent when they break rather than trying for line coverage:

| File | What it pins down |
|---|---|
| `test_draft_expiry.py` | Manual Draft deletion: only a Draft can be deleted this way, it takes its staged candidates with it, and an activated batch is refused. |
| `test_access_scoping.py` | Per-creator batches vs uploader-agnostic candidates, over both the queryset helpers and HTTP. |
| `test_candidate_identity.py` | Only four Aadhaar digits are storable, a full 12-digit number is rejected rather than truncated, and two people sharing a suffix are not treated as duplicates. |
| `test_email_delivery.py` | Status is never "sent" when the provider failed, a failure always carries a reason, the reason never echoes an API key, and the retry sweep skips links that are opened, expired, or on a batch that may not invite. |
| `test_hardening.py` | Unhandled errors return JSON without leaking the exception, rate limits actually return 429, readiness fails when the database is down, and stored evidence URLs carry no credential. |
| `test_proctoring_warnings.py` | Which causes get one warning and which end the attempt outright, that the camera going off is warnable, and that the warning budget is shared across all causes. |
| `test_batch_validation.py` | That a link window shorter than the exam duration is refused, in both directions, while the one pre-existing batch that violates it stays editable. |
| `test_spa_fallback.py` | That a cold load of a client-side route returns the SPA shell rather than a 404 - the `/t/<token>` link in every invitation email is always entered this way - while an unmatched `/api/` path still 404s instead of quietly returning HTML. |
| `test_smoke.py` | That the suite cannot reach a real database. |

**The suite runs against in-memory SQLite and never touches PostgreSQL.** That is enforced by
`config/settings_test.py`, which `pytest.ini` selects as the settings module - not by a conftest
hook, which is too late (pytest-django has already cached the connection by then, and an earlier
version of this suite would have created and dropped `test_QA_TalentDB` on the shared server).
`test_smoke.py::test_test_database_is_isolated` is the guard; if it ever fails, stop.

Because the schema is built from the models (`--no-migrations`, needed because migration 0013
contains PostgreSQL-only SQL), the suite does not exercise the migration history.
`python manage.py makemigrations --check --dry-run` is what guards that, and belongs in CI
alongside pytest.

## Deployment

### Running it

```bash
docker compose up --build
```

That brings up four services: the Django app under gunicorn, an nginx container serving the
built SPA, Redis, and a scheduler running the three housekeeping commands on a loop. The app is
reached on <http://localhost:8080>.

**nginx proxies `/api/` to the backend, so the frontend and API share an origin.** That is the
intended topology, not a convenience: same-origin means no CORS preflight at all, and it means
the refresh-token cookie's `SameSite=Strict` is correct. Splitting them onto genuinely different
sites is what makes that cookie a hazard - the browser silently withholds it on every refresh
and users are logged out mid-session with nothing logged anywhere. If you must split them, set
`REFRESH_COOKIE_SAMESITE=None` and serve over HTTPS.

Postgres is deliberately **not** a compose service: the database is a managed instance holding
real candidate data, and defaulting the stack to a throwaway local one invites running
migrations against the wrong target. Point `DB_*` in `Backend/.env` at the real thing.

For a host without Docker, `Backend/Dockerfile` and `Backend/docker-entrypoint.sh` document the
same sequence: `migrate`, `collectstatic`, then `gunicorn --config gunicorn.conf.py
config.wsgi:application`.

### Azure App Service (staging)

`azure-pipelines.yml` builds and deploys to a single App Service in `rg-talentgate-staging`:

| Resource | Name |
|---|---|
| App Service (Django + SPA) | `app-talentgate-staging` |
| App Service plan | `asp-talentgate-staging` (Linux B1) |
| PostgreSQL flexible server | `recruitmentapptitudeteststaging` (database `QA_TalentDB`) |
| Storage (proctoring evidence) | `sttalentgatestaging`, container `proctoring-evidence` |

**One App Service serves both the API and the frontend**, for the same-origin reason above.
There is no Static Web App: routing the API through one would have meant the Standard plan and,
worse, a hard 45-second ceiling on every `/api` request — which `gunicorn.conf.py` deliberately
sets to 120s because a few thousand candidate rows arrive in a single upload. Instead the pipeline
copies the Vite build into `Backend/frontend/` (`FRONTEND_DIST`), where WhiteNoise serves the
hashed bundles and the catch-all in `config/urls.py` returns `index.html` for client-side routes.
`config/spa.py` has the details.

Because App Service runs the app from a zip on its own Python image, it never invokes
`docker-entrypoint.sh`. `Backend/startup.sh` is the equivalent and is set as the startup command;
**it is the only thing that applies migrations on this host**, so keep the two files in step.

The pipeline needs one thing that is not in source control: an ARM service connection named
`TalentGate-Staging` (the `azureServiceConnection` variable), scoped to `rg-talentgate-staging`.

### Deployment status

Staging is deployed. Build `20260825.3` ran from `main` on 2026-08-25 and completed all three jobs
— backend tests, frontend build and packaging, and `Deploy App Service` — so the
`TalentGate-Staging` service connection exists and works, and `app-talentgate-staging` is running
the packaged app. The pipeline's default branch is `main`. The database behind it holds real
candidate data.

`DB_PASSWORD`, `SECRET_KEY`, and all four `GRAPH_*` values are already set as App Service
application settings. Set them the same way if the App Service is ever rebuilt — without
`DB_PASSWORD`, `startup.sh` fails at `migrate` and the site never starts; without the Graph values
it starts fine but invitation emails don't send.

```bash
az webapp config appsettings set -g rg-talentgate-staging -n app-talentgate-staging \
  --settings DB_PASSWORD='...' GRAPH_TENANT_ID='...' GRAPH_CLIENT_ID='...' \
             GRAPH_CLIENT_SECRET='...' GRAPH_SENDER='...'
```

**Only `main` deploys**; feature branches build and test and stop there. The service connection is
validated at queue time for *every* run, including feature-branch runs whose deploy stage the
condition skips, so deleting or renaming it breaks all builds rather than only deployments.

**The deploy stage waits for a human.** The `talentgate-staging` environment carries a required
approval, so a push to `main` builds and tests without interruption and then pauses before
deploying. That gate exists because staging runs against the Postgres server holding real candidate
data, and there should be no unattended path from `git push` to that data. Approvals expire after
30 days. Validate risky changes on a `feature/*` branch first — the trigger covers them, and the
deploy stage's branch condition skips them, so the gate is never even reached.

#### Migration state: `main` and the database are in step

Checked on 2026-08-25: `main` contains all 17 `api` migrations, through
`0017_batch_college_name_optional`, and `makemigrations --check` reports no uncommitted model
changes. The server was recorded as having all 17 applied on 2026-08-24, so **a deploy applies none
of them**. That includes `0013_candidate_aadhaar_last4`, whose `UPDATE candidates SET
aadhaar_number = RIGHT(...)` is deliberately irreversible — it has already run, so there are no
full Aadhaar numbers left to lose.

**Never deploy a branch whose migrations stop short of the database.** `migrate` is a no-op against
history rows whose files it cannot see, so nothing warns you at deploy time: the schema has
`aadhaar_last4` where older code still expects `aadhaar_number`, and the failure surfaces at
runtime. Every other branch in this repo is in exactly that position — `fix/auth-refresh-dedupe`
stops at `0005`, `phase-3-dashboards-candidates` at `0007`, `refactor/modular-architecture` at
`0011`, `phase-4-ta-portal-hardening` at `0012`. Only `main` is safe to deploy against this
database.

Re-verify with `python manage.py showmigrations api` against the real server if time has passed.
The server keeps 7 days of automatic backups with point-in-time restore; note that restoring
produces a *new* server rather than rewinding this one, so recovery also means repointing `DB_HOST`.

### Scheduled jobs

Wire the three commands in the table above into whatever scheduler the host has. Ready-made:

| Host | Use |
|---|---|
| Docker | Already running as the `scheduler` service in `docker-compose.yml`. |
| Linux/cron | `deploy/crontab.example` |
| Windows | `deploy/register-scheduled-tasks.ps1 -BackendPath C:\path\to\Backend` (elevated) |
| App Service (this deployment) | Already running, as background loops in `Backend/startup.sh`. |

App Service is the awkward one: Linux App Service has no cron, and WebJobs are Windows-only, so
`startup.sh` backgrounds a loop per command before handing off to gunicorn. This is a compromise,
not the intended shape - the loops live and die with the web container, so a restart silently
stops them until it comes back up, and scaling to a second instance would run every job twice.
Move them to a Container Apps job or another external trigger if this outgrows staging.

The reason it is worth doing at all rather than leaving the jobs unscheduled: an unscheduled
`process_email_queue` means invitation emails are never sent, and **nothing surfaces that**. The
invite is correctly recorded as issued, the UI says so, and the rows just accumulate at
`email_status=QUEUED` while candidates wait for links that will never arrive. Check with
`python manage.py process_email_queue --dry-run`, which reports the queue without sending.

### Before go-live

`python manage.py check --deploy` reports most of this itself - the `api.W00x` warnings come
from `Backend/api/checks.py` and cover configuration Django's own checks know nothing about.

- **Rotate `SECRET_KEY` and the database password.** Both currently exist only as values a
  developer entered locally into `.env`. `SECRET_KEY` also signs every JWT, so a leaked one lets
  anyone mint a valid staff token. Generate one with:
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- **Rotate the Azure Storage account key** if it has ever been shared. This is now safe to do:
  evidence URLs are signed at read time (`blob_storage.fresh_read_url`), so rotation no longer
  breaks historical evidence. It would have before - stored URLs used to carry a 365-day token
  and nothing re-signed them.
- **Set `REDIS_URL`.** Without it, rate limiting and login lockout count in a per-process cache,
  so every limit is effectively multiplied by the worker count and the lockout can be evaded by
  landing on a different worker. Reported as `api.W001`.
- **Set `TRUST_X_FORWARDED_FOR=True`, but only behind a proxy that overwrites the header.**
  Without it every request appears to come from the proxy, so all IP rate limits collapse into
  one shared bucket and audit logs record the proxy's address. `Frontend/nginx.conf` sets rather
  than appends `X-Forwarded-For`, which is what makes trusting it safe. It also enables
  `SECURE_PROXY_SSL_HEADER`, without which `ENABLE_SSL_REDIRECT` causes a redirect loop.
- **Set `ENABLE_SSL_REDIRECT=True`** once TLS termination is confirmed. This also switches HSTS on.
- **Tighten `CORPORATE_EMAIL_DOMAIN`** - it currently includes a public webmail domain that was
  added for deliverability testing. Reported as `api.W004`.
- **Set `SUPPORT_EMAIL`** to a monitored mailbox; it is printed in candidate emails as the
  contact for technical problems. Reported as `api.W003`.
- **Set `FRONTEND_ORIGIN` to the deployed URL.** Invitation links are built from it, and a
  localhost value produces links that only work on the machine reading the email - they send
  successfully and render a working button, so there is nothing to notice until a candidate
  reports that the link does nothing. Check it before the first real invite.
- **Set `SENTRY_DSN`** if you want error reporting; nothing is sent anywhere without it.
- **`DB_SSLMODE` defaults to `require`.** Only set it to `disable` for a local Postgres with no
  TLS configured.

### Deliberately not installed

`/admin/` is **not routed** and `django.contrib.admin` is not in `INSTALLED_APPS`. Every model
had been registered there with no write protection, against `django.contrib.auth.User` - a
different user table from the one this app authenticates with. That made it a full bypass of the
app's own RBAC: an editable `AuditLog`, a readable `Question.correct_option`, and a login path
with none of the rate limiting or lockout the real login has. Staff administration lives in the
app's own User Management screen, which enforces the real permissions.
- `ENABLE_SSL_REDIRECT` and `TRUST_X_FORWARDED_FOR` gate production transport/cookie hardening
  behind explicit opt-in flags - set both `True` behind a TLS-terminating proxy.
- `CORPORATE_EMAIL_DOMAIN` currently includes a non-corporate domain for testing purposes -
  confirm this is tightened before go-live.
- The two scheduled commands above must be wired into the host's scheduler.

## Architectural decisions log

- **Batch visibility is per-creator; candidate visibility is not**: a Staffing User sees only
  the batches they created (an Administrator sees all), but **All Candidates shows every
  candidate regardless of who uploaded them**. The asymmetry is deliberate - the batch list is
  a work queue, the candidate list is a directory of people. Both go through the single seam in
  `Backend/api/services/access.py`, and both directions are pinned by
  `Backend/api/tests/test_access_scoping.py`, because each has been reversed once already.
- **Draft and Cancelled batches are excluded from the default dashboard/list view** but remain
  fully reachable via an explicit status filter - see `Backend/api/services/batch_status_filter.py`.
- **Candidate/question bulk uploads are two-phase**: validate first (nothing written), then
  import: the import re-validates from scratch rather than trusting the reviewed payload, so a
  tampered request can't slip an invalid row through.
- **Duplicate detection is a status, not a hard block, across batches** (a candidate who
  appears in an earlier batch is flagged for the TA to judge), but **is a hard block within one
  upload** (the same Aadhaar or email twice in one file is treated as a data-entry mistake, not
  a legitimate repeat, and only the first occurrence is kept).
