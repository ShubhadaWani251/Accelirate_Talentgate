# TalentGate

Candidate evaluation platform for Accelirate's fresher hiring pipeline: administrators and
Staffing Users (TAs) configure hiring batches, bulk-upload candidates, validate and deduplicate
them, run duplicate/cooling-off checks against candidate history, send assessment invitations,
manage a shared question bank, and review results.

## Status

The TA/Admin portal (auth, batches, candidate upload & validation, question bank, user
management, dashboards, email notifications) is built and in active use against a shared Azure
Postgres instance. **The candidate-facing assessment flow does not exist yet** — invitation
emails currently link to a `/t/<token>` route that has no frontend page and no backend exam
endpoints behind it. That's the next major piece of work, not a bug in what's described below.

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
- **Several dependencies in `requirements.txt`/`package.json` aren't wired into the app yet**
  (celery, sentry-sdk, drf-yasg, django-oauth-toolkit, prometheus_client, pytest, factory_boy,
  Faker, numpy on the backend; jwt-decode, dayjs, bootstrap-icons on the frontend). These are
  kept intentionally as placeholders for planned work (task queue, error tracking, API docs,
  a real test suite) rather than removed as dead weight - remove them only once you're
  confident that work isn't happening.

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

## Testing

There is currently no meaningful automated test suite (`Backend/api/tests.py` is Django's
stock boilerplate). Verification during development has relied on one-off scripts run inside a
rolled-back database transaction (never committed) plus manual browser walkthroughs. Building a
real test suite is an open item, not something this README can claim is already covered.

## Deployment notes

- Rotate `SECRET_KEY` and the database password for any real deployment; both currently exist
  only as values a developer entered locally into `.env`.
- `ENABLE_SSL_REDIRECT` and `TRUST_X_FORWARDED_FOR` gate production transport/cookie hardening
  behind explicit opt-in flags - set both `True` behind a TLS-terminating proxy.
- `CORPORATE_EMAIL_DOMAIN` currently includes a non-corporate domain for testing purposes -
  confirm this is tightened before go-live.
- The candidate/exam-taking flow (see Status above) has no backend endpoints or frontend
  routes yet; invitation emails will link to a route that 404s until that's built.

## Architectural decisions log

- **Batch visibility is org-wide, not per-owner**: any Staffing User can see and act on any
  batch, not just ones assigned to them - see `Backend/api/services/access.py` for the single
  seam this is enforced through.
- **Draft and Cancelled batches are excluded from the default dashboard/list view** but remain
  fully reachable via an explicit status filter - see `Backend/api/services/batch_status_filter.py`.
- **Candidate/question bulk uploads are two-phase**: validate first (nothing written), then
  import: the import re-validates from scratch rather than trusting the reviewed payload, so a
  tampered request can't slip an invalid row through.
- **Duplicate detection is a status, not a hard block, across batches** (a candidate who
  appears in an earlier batch is flagged for the TA to judge), but **is a hard block within one
  upload** (the same Aadhaar or email twice in one file is treated as a data-entry mistake, not
  a legitimate repeat, and only the first occurrence is kept).
