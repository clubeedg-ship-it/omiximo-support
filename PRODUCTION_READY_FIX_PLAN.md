# Production-Ready Fix Plan

This handoff is for a coding assistant implementing the issues found in the whole-codebase review. The repository is a FastAPI/SQLAlchemy backend plus Vite/React frontend.

Current verification baseline from review:

- Backend tests: `cd backend && uv run pytest -q` -> `252 passed`, 3 FastAPI deprecation warnings.
- Backend compile: `cd backend && uv run python -m compileall -q app` -> passed.
- Frontend tests: `cd frontend && npm test -- --run` -> `41 passed`.
- Frontend build: `cd frontend && npm run build` -> passed.
- Frontend lint: `cd frontend && npm run lint` -> failed with 5 errors.
- Alembic head: `003`; local DB current check failed because local Postgres credentials were invalid.

Do not overwrite unrelated user changes. At time of review, existing dirty/untracked files included:

- Modified: `backend/app/models/support_thread.py`
- Untracked: `.playwright-mcp/`, `backend/uv.lock`, `frontend/README.md`

## Goals

Make the app production-ready from day one for a single tenant.

Single tenant does not mean no auth. It means authorization can stay simple: authenticated Clerk users plus a backend allowlist. Every operational API should require identity, and audit rows should record the real actor instead of a hardcoded email.

## Priority 1: Production Blockers

### 1. Add Clerk Authentication To Backend

Problem:

- All `/api/v1/*` endpoints are currently unauthenticated.
- If reachable by untrusted users, anyone can list customer threads, read messages, create accounts/templates, approve replies, escalate threads, resolve classification flags, and trigger operational behavior.
- CORS is not authentication and does not protect direct API requests.

Target behavior:

- `/health` remains public.
- Every `/api/v1/*` route requires a valid Clerk JWT.
- JWT validation must verify issuer, audience if configured, signature, and expiration.
- Backend exposes a dependency that returns the authenticated user context.
- All mutating audit actions use the authenticated Clerk user id/email as actor.

Suggested backend files:

- Add `backend/app/auth.py` or `backend/app/core/auth.py`.
- Update `backend/app/config.py`.
- Update `backend/app/api/router.py` or each router to apply auth dependency globally.
- Update endpoint handlers that currently take `actor` from body or hardcode actor values.

Suggested config:

```text
ENVIRONMENT=development|production|test
CLERK_ISSUER=https://<your-clerk-domain>
CLERK_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
CLERK_AUDIENCE=<optional-api-audience>
ALLOWED_ADMIN_EMAILS=admin@example.com,ops@example.com
ALLOWED_EMAIL_DOMAIN=example.com
```

Implementation notes:

- Prefer a small `CurrentUser` model/dataclass with fields like `user_id`, `email`, `claims`.
- Extract bearer token from `Authorization: Bearer <jwt>`.
- Cache JWKS keys with reasonable TTL to avoid fetching on every request.
- In tests, avoid network calls by overriding the dependency or using a fake verifier.
- Make auth enforcement explicit in tests: unauthenticated requests to protected endpoints return `401`.

Dependencies:

- Use a JWT/JWKS library already available if present, otherwise add appropriate backend dependency. Common choices are `PyJWT[crypto]` or `python-jose[cryptography]`.
- If adding a dependency, update `backend/pyproject.toml` and lock file if the project uses one.

Tests to add/update:

- Backend conftest auth override fixture for normal tests.
- Test unauthenticated `/api/v1/threads` returns `401`.
- Test unauthorized authenticated user outside allowlist returns `403`.
- Test allowed authenticated user can call a protected route.
- Test audit actor is populated from authenticated user, not request body/hardcoded email.

### 2. Add Single-Tenant Authorization

Problem:

- Clerk authentication alone proves identity, not that the user belongs to this support team.

Target behavior:

- Authenticated users are allowed only if their email is in `ALLOWED_ADMIN_EMAILS` or their email domain matches `ALLOWED_EMAIL_DOMAIN`.
- If neither allowlist is configured in production, startup should fail.
- In development/test, allow a documented bypass only through explicit test/development settings.

Implementation notes:

- Keep this simple. Do not add tenant tables unless there is a real multi-tenant requirement.
- Return `403` for authenticated but not allowed users.

### 3. Fix Failed Human Send Persistence

Problem:

- In `backend/app/api/threads.py`, `approve_thread()` catches Mirakl send exceptions, sets `thread.status = FAILED`, writes `human_send_failed`, then raises `HTTPException`.
- `get_db()` rolls back the session on any exception, so the failed status and audit row are lost.

Current location:

- `backend/app/api/threads.py`, around the `except Exception as exc:` block in `approve_thread()`.
- `backend/app/database.py`, `get_db()` commits after yield and rolls back on exception.

Target behavior:

- If Mirakl send fails during manual approval, persist:
  - `SupportThread.status = FAILED`
  - `SupportThread.updated_at`
  - audit log action `human_send_failed`
- Return HTTP `502` to caller.
- The failure state and audit row must still exist after the response.

Implementation options:

- Option A: Commit inside the exception block before raising `HTTPException`, then ensure later rollback does not undo already committed data.
- Option B: Return a `JSONResponse` after committing instead of raising.
- Option C: Use a separate session for failure audit persistence.

Preferred approach:

- Keep it simple: explicitly `await db.commit()` in the failure branch after writing the audit row, then raise `HTTPException`. Confirm SQLAlchemy rollback after commit is harmless in the dependency teardown.

Tests to add:

- Patch `MiraklClient.send_reply` to raise.
- Call `PUT /api/v1/threads/{id}/approve`.
- Assert response status is `502`.
- Reload thread and assert status is `FAILED`.
- Query audit logs and assert `human_send_failed` exists.

### 4. Remove Unsafe Default Secrets

Problem:

- `backend/app/config.py` has a hardcoded default `FERNET_KEY`.
- If `FERNET_KEY` is missing in production, encrypted marketplace API keys are protected by a public key.

Target behavior:

- In production, startup fails if `FERNET_KEY` is missing, a placeholder, or the known default value.
- In production, startup also fails if Clerk configuration is incomplete.
- If webhooks are enabled/exposed, production should require `MIRAKL_WEBHOOK_SECRET` or make the insecure state explicit.

Suggested files:

- `backend/app/config.py`
- Potentially `backend/app/main.py` startup validation.

Implementation notes:

- Add `ENVIRONMENT: str = "development"`.
- Add `Settings.validate_production()` or a standalone function called during app startup/import.
- Tests should override env/config safely.

Tests to add:

- Production config with default `FERNET_KEY` raises configuration error.
- Development/test config remains usable.

## Priority 2: Functional Correctness

### 5. Implement Dashboard Search End-To-End

Problem:

- Frontend tracks `filters.search`, but `frontend/src/lib/api.ts` never sends it.
- Backend `/api/v1/threads` has no `search` query parameter.
- The search box says “Search by order ID or message...” but does not filter.

Target behavior:

- Search filters threads by at least:
  - `mirakl_order_id`
  - `mirakl_thread_id`
  - `customer_message`
- Search should be case-insensitive on Postgres.

Suggested backend files:

- `backend/app/api/threads.py`

Suggested frontend files:

- `frontend/src/lib/api.ts`
- Existing UI may not need changes beyond sending the param.

Backend implementation notes:

- Add `search: str | None = Query(default=None, min_length=1)`.
- Use `ilike` for Postgres-compatible case-insensitive search.
- Apply same filter to count and data queries by building one filtered base query.

Frontend implementation notes:

- Include `filters.search` in `fetchThreads()` query string.
- Consider debounce if search causes excessive requests, but not required for first fix.

Tests to add:

- Backend test: search by order id returns matching thread only.
- Backend test: search by message fragment returns matching thread only.
- Frontend test: `fetchThreads({ search: 'abc' })` calls URL with `search=abc`, or component-level behavior if API is mocked.

### 6. Return Marketplace Details Expected By UI

Problem:

- Frontend type `Thread` allows `marketplace_account?: MarketplaceAccount`.
- Dashboard renders `thread.marketplace_account?.marketplace`.
- Backend `ThreadResponse` only returns `marketplace_account_id`, so the UI falls back to raw UUIDs.

Target behavior:

- Dashboard should display marketplace name without additional per-row requests.

Preferred minimal backend API shape:

- Add `marketplace_name: str | None` to `ThreadResponse`.
- Populate it in list/detail responses.
- Update frontend type/rendering to use `marketplace_name`.

Alternative:

- Return nested `marketplace_account`, but use eager loading to avoid N+1 queries.

Suggested files:

- `backend/app/schemas/thread.py`
- `backend/app/api/threads.py`
- `frontend/src/lib/types.ts`
- `frontend/src/components/threads/thread-table.tsx`
- `frontend/src/components/review/review-pane.tsx` if needed.

Tests to add:

- Backend list response includes marketplace name.
- Frontend renders marketplace name from API response.

### 7. Fix Classification Category Options

Problem:

- UI flag dialog category dropdown omits backend classifier categories.
- Current UI categories include values like `tracking_update`, `return_inquiry`, `complaint`.
- Backend classifier commonly returns categories such as `shipping_delay`, `missing_parcel`, `return_request`, `warranty_claim`, `defect_report`, `invoice_request`, `wrong_item`, `damaged_item`, `order_cancellation`, `general_inquiry`.
- Reviewers cannot submit many valid corrections from the UI.

Current location:

- `frontend/src/components/review/action-bar.tsx`, `CATEGORIES` constant.
- Backend classifier categories listed in `backend/app/services/classifier.py` system prompt.

Target behavior:

- UI category options include all backend classifier well-known categories.

Immediate fix:

```text
shipping_delay
missing_parcel
return_request
warranty_claim
defect_report
invoice_request
wrong_item
damaged_item
order_cancellation
general_inquiry
tracking_update
delivery_confirmation
complaint
```

Better follow-up:

- Add backend endpoint to expose known categories or template categories.
- Frontend fetches category options from backend.

Tests to add:

- Frontend test verifies `shipping_delay`, `return_request`, and `warranty_claim` are selectable.

## Priority 3: CI And Maintainability

### 8. Fix Frontend Lint Failures

Current command:

```bash
cd frontend && npm run lint
```

Current failures:

- `frontend/src/components/ui/badge.tsx`: `react-refresh/only-export-components` because file exports both component and `badgeVariants`.
- `frontend/src/components/ui/button.tsx`: same issue for `buttonVariants`.
- `frontend/src/components/ui/input.tsx`: empty interface equivalent to supertype.
- `frontend/src/components/ui/textarea.tsx`: empty interface equivalent to supertype.
- `frontend/src/pages/reports.tsx`: React hooks immutability violation from reassigning `cumulative` during render.

Target behavior:

- `npm run lint` passes.

Implementation notes:

- Move `badgeVariants` and `buttonVariants` into separate non-component files, or stop exporting variants if unused.
- Replace empty interfaces with type aliases:
  - `type InputProps = React.InputHTMLAttributes<HTMLInputElement>`
  - `type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>`
- Rewrite donut chart segment generation without mutating a render-local variable. Example approach: use `reduce` returning `{ segments, cumulative }`.

Tests:

- Existing frontend tests should continue passing.
- `npm run lint` must pass.

### 9. Add CI Gates

Recommended CI commands:

Backend:

```bash
cd backend
uv run pytest -q
uv run python -m compileall -q app
```

Frontend:

```bash
cd frontend
npm run lint
npm test -- --run
npm run build
```

Migration check:

- Run Alembic against a disposable Postgres service.
- Confirm migrations apply from empty DB to head.
- Confirm `alembic heads` reports a single head.

### 10. Add Production Startup Validation

Problem:

- App starts background loops automatically in `backend/app/main.py`.
- In multi-worker deployments, each worker may start poller/auto-send/SLA loops unless deployment is constrained to one worker.
- This can cause duplicate external work if locking is incomplete.

Target behavior:

- Background workers are explicitly enabled with config, e.g. `ENABLE_BACKGROUND_WORKERS=true`.
- Production deployment docs or config guarantee exactly one worker process runs background tasks.
- If multiple API workers are desired, run background jobs separately.

Suggested files:

- `backend/app/config.py`
- `backend/app/main.py`
- Deployment docs if present.

Implementation notes:

- Add `ENABLE_BACKGROUND_WORKERS: bool = True` for dev or `False` for production by default, depending deployment plan.
- If disabled, app serves HTTP only.
- If enabled, log clearly that background workers are running.

## Frontend Clerk Integration

After backend auth is implemented, frontend must send Clerk session tokens.

Suggested frontend packages:

- `@clerk/clerk-react`

Suggested config:

```text
VITE_CLERK_PUBLISHABLE_KEY=<key>
```

Suggested files:

- `frontend/src/main.tsx` or `frontend/src/App.tsx`: wrap app in `ClerkProvider`.
- `frontend/src/lib/api.ts`: attach `Authorization: Bearer <token>`.
- `frontend/src/components/layout/header.tsx`: show user/sign-out controls.
- Add a sign-in route or use Clerk components.

Implementation approach:

- Create a small API token provider layer rather than importing Clerk directly into every API function.
- Example: `setAuthTokenGetter()` or React hook wrappers around API calls.
- With React Query, hooks can call `getToken()` and pass token to API functions.

Target behavior:

- Unauthenticated users see sign-in UI.
- Authenticated users get API data only if backend allowlist passes.
- All mutations identify actor from backend auth context.

## Audit Actor Cleanup

Problem:

- Frontend sends hardcoded `actor: 'admin@omiximo.nl'` in multiple places.
- Backend also trusts user-provided actor fields.

Target behavior:

- Backend derives actor from authenticated `CurrentUser`.
- Request body actor fields are removed or ignored for authenticated endpoints.

Suggested files:

- `backend/app/schemas/thread.py`: remove or deprecate `actor` in approval/escalation requests.
- `backend/app/schemas/classification.py`: remove or deprecate `actor` in flag/resolve requests.
- `backend/app/api/threads.py`: use `current_user.actor`.
- `backend/app/api/classification.py`: use `current_user.actor`.
- `frontend/src/components/review/action-bar.tsx`: stop sending actor.
- `frontend/src/pages/classification.tsx`: stop sending actor.
- `frontend/src/lib/types.ts`: update payload types.

Migration strategy:

- For fastest compatibility, make actor optional in request schemas and ignore client-provided actor when auth is present.
- Later remove actor from API docs once frontend is updated.

Tests:

- Approval audit actor equals test authenticated user.
- Escalation audit actor equals test authenticated user.
- Classification flag actor equals test authenticated user.
- Flag resolution actor equals test authenticated user.

## Acceptance Checklist

All must pass before considering this production-ready:

```bash
cd backend && uv run pytest -q
cd backend && uv run python -m compileall -q app
cd frontend && npm run lint
cd frontend && npm test -- --run
cd frontend && npm run build
```

Manual/API checks:

- `/health` works without auth.
- `/api/v1/threads` returns `401` without auth.
- `/api/v1/threads` returns `403` for authenticated but unallowed user.
- `/api/v1/threads` returns `200` for allowed Clerk user.
- Failed manual approval returns `502` and persists `FAILED` plus `human_send_failed` audit row.
- Dashboard search filters by order id and message.
- Dashboard shows marketplace name, not account UUID.
- Flag classification dropdown includes backend classifier categories.
- Production config refuses unsafe default `FERNET_KEY`.

## Recommended Implementation Order

1. Fix failed human send persistence and add tests.
2. Add production config validation for secrets.
3. Add backend Clerk auth dependency and test overrides.
4. Apply auth to `/api/v1/*` and replace hardcoded/trusted actor handling.
5. Add frontend Clerk provider and token injection.
6. Implement search end-to-end.
7. Add marketplace display field end-to-end.
8. Fix classification categories.
9. Fix frontend lint errors.
10. Add or update CI workflow.

