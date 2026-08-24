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

## Development commands

| | Backend | Frontend |
|---|---|---|
| Run dev server | `python manage.py runserver` | `npm run dev` |
| Build for production | - | `npm run build` |
| Lint | - | `npm run lint` |
| Django system checks | `python manage.py check` | - |
| Apply migrations | `python manage.py migrate` | - |
| Create a migration | `python manage.py makemigrations api` | - |
| Run tests | `python -m pytest` | - |
| Check for uncommitted model changes | `python manage.py makemigrations --check --dry-run` | - |
| Production readiness check | `python manage.py check --deploy` | - |

### Scheduled jobs (required in any real deployment)

Three housekeeping commands have to run on a timer. None is optional: without them, abandoned
exam attempts sit `in_progress` forever, unfinalized draft batches are never cleaned up, and an
invitation email interrupted by a deploy is never retried.

There is no task queue - these are plain management commands, driven by whatever scheduler the
host already provides (cron, Windows Task Scheduler, an Azure WebJob, or the `scheduler` service
in `docker-compose.yml`). See **Deployment** below for ready-made configurations.

| Command | Suggested interval | What it does |
|---|---|---|
| `python manage.py finalize_expired_attempts` | every 5-15 min | Finalizes exam attempts still `in_progress` past their deadline, and ones whose candidate never started before the invitation link expired. |
| `python manage.py delete_expired_draft_batches` | every 15-60 min | **Deletes** Draft batches not finalized within 24 hours of creation, together with their staged candidates. Run `--dry-run` first to see what it would remove. |
| `python manage.py retry_stalled_invite_emails` | every 15 min | Re-sends invitation emails left `queued` by an interrupted send. Emails go out on a daemon thread inside the web worker, so a deploy's SIGTERM kills any still in flight and they would otherwise sit `queued` forever, reading as "in progress". Skips rows whose link is already opened or expired. |

All three are safe to run more often than suggested - each is idempotent and does nothing when
there is nothing to process. `delete_expired_draft_batches` really deletes rows, so read
`Backend/api/services/draft_expiry.py` before changing the 24-hour window.

## Testing

```bash
cd Backend && python -m pytest
```

159 tests, a few seconds. `pytest.ini` and `Backend/api/tests/` hold the suite; it covers
the invariants that are silent when they break rather than trying for line coverage:

| File | What it pins down |
|---|---|
| `test_draft_expiry.py` | The 24-hour rule: clock starts at creation and is **not** reset by edits or uploads, activation stops expiry permanently, deletion takes staged candidates with it, the sweep is idempotent. |
| `test_access_scoping.py` | Per-creator batches vs uploader-agnostic candidates, over both the queryset helpers and HTTP. |
| `test_candidate_identity.py` | Only four Aadhaar digits are storable, a full 12-digit number is rejected rather than truncated, and two people sharing a suffix are not treated as duplicates. |
| `test_email_delivery.py` | Status is never "sent" when the provider failed, a failure always carries a reason, the reason never echoes an API key, and the retry sweep skips links that are opened, expired, or on a batch that may not invite. |
| `test_hardening.py` | Unhandled errors return JSON without leaking the exception, rate limits actually return 429, readiness fails when the database is down, and stored evidence URLs carry no credential. |
| `test_proctoring_warnings.py` | Which causes get one warning and which end the attempt outright, that the camera going off is warnable, and that the warning budget is shared across all causes. |
| `test_batch_validation.py` | That a link window shorter than the exam duration is refused, in both directions, while the one pre-existing batch that violates it stays editable. |
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

### Scheduled jobs

Wire the three commands in the table above into whatever scheduler the host has. Ready-made:

| Host | Use |
|---|---|
| Docker | Already running as the `scheduler` service in `docker-compose.yml`. |
| Linux/cron | `deploy/crontab.example` |
| Windows | `deploy/register-scheduled-tasks.ps1 -BackendPath C:\path\to\Backend` (elevated) |

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
- The two scheduled commands above must be wired into the host's scheduler. Draft-batch expiry
  in particular has a lazy fallback (an expired draft is deleted the moment anyone touches it)
  and a queryset filter that hides expired drafts immediately, but neither is a substitute:
  only the scheduled job removes a draft that nobody ever looks at again.

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
