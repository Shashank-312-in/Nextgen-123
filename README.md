# NextGen SMS (Version 1.1) — API & Test Suite

For full architectural specifications, SMS routing invariants, schema details, and release notes, see:
- [VERSION.md](file:///c:/Users/vcet%20CSD%20HOD/Downloads/NextGen_SMS_live_cleaned/VERSION.md) — Authoritative Version 1.1 Release Notes & Architecture Guide
- [IMPLEMENTATION_STATE.md](file:///c:/Users/vcet%20CSD%20HOD/Downloads/NextGen_SMS_live_cleaned/IMPLEMENTATION_STATE.md) — Implementation state and SMS routing invariants

Real pytest + FastAPI TestClient tests against your actual `api/` and `db_proxy/` code.
No mocks — every test hits your real MySQL through your real routes.

## What's covered (Phase 1)
- **Auth** (`test_01_auth.py`) — login envelope shape, rate limiting,
  token validation, /me, register/change-password validation, OTP input
  validation, logout. 18 tests.
- **Students** (`test_02_students.py`) — RBAC (HOD/ADMIN-only writes),
  every validation rule in `validate_student()`, full create→read→update→
  delete lifecycle on one tagged throwaway record, Aadhaar-masking check.
  19 tests.
- **Attendance** (`test_03_attendance.py`) — staff-only RBAC on every
  mutating route, get-or-create session idempotency, LAB duration
  override, and the critical "mark-all-present must not write the DB"
  invariant. 18 tests.

**55 tests.**

## Phase 2 — full remaining surface

- **Faculty & Accounts** (`test_04_faculty_accounts.py`) — HOD/ADMIN RBAC,
  permission-update validation (with safe round-trip + restore), and the
  three self-protection guards (can't deactivate/delete yourself, can't
  reset-password on a non-STUDENT account). 18 tests.
- **Subjects/Semesters + Academic Calendar** (`test_05_subjects_calendar.py`)
  — RBAC, validation, duplicate-code conflict (create+cleanup), calendar
  upload/delete guards. Includes a dedicated test for the **documented
  ADMIN role-check gap** in `routes_subjects.py` (see below). 23 tests.
- **Protected Files + Problem Reports** (`test_06_files_reports.py`) —
  path-traversal attempts (the actual security property this route
  exists for), subdir authorization, full report submit→list→resolve
  lifecycle. 18 tests.
- **Dashboard + Self-service** (`test_07_dashboard_me.py`) — role-aware
  dashboard root, session drill-down RBAC, HOD-only audit/SMS log access
  (no ADMIN carve-out here either — different from the POST mutators),
  account/profile self-edit round-trip (with restore), roll-no injection
  guard. 35 tests.
- **Database Proxy Relay** (`test_08_db_proxy.py`) — campus MySQL proxy
  transaction management, authorization, rollback, and error handling. 8 tests.

**157 tests total across all test suites.**

### The ADMIN role-check gap, explicitly

`routes_faculty.py`'s HOD check allows `(HOD, ADMIN)`. `routes_subjects.py`'s
does not — it's `role != "HOD"` with no ADMIN case. `test_05_subjects_calendar.py`
has a test that asserts the **current** behavior (ADMIN gets 403 on
`/api/subjects`) and explains in its own docstring what to do if that's
ever intentionally changed. This is not a bug the suite is silently
tolerating — it's a known inconsistency worth a human decision, and the
test's job is to make sure nobody changes it by accident. It only runs
if you set `TEST_ADMIN_USERNAME`/`TEST_ADMIN_PASSWORD`; otherwise it
skips cleanly.

## Setup (one-time)

```bash
# 1. Put this tests/ folder + scripts anywhere, e.g. inside your project repo
# 2. Install test deps (uses your existing requirements-dev.txt too)
pip install --break-system-packages -r requirements.txt -r requirements-dev.txt pytest pytest-html

# 3. Configure real credentials — NEVER commit this file
cp .env.test.example .env.test
nano .env.test   # fill in MYSQL_* (same as your app uses) + 3 test accounts
```

**Test accounts**: use real, already-existing, active accounts (one HOD,
one FACULTY, one STUDENT) that do NOT currently have a forced password
change pending. The suite logs in as them — it never creates or deletes
login accounts itself.

## Running it

```bash
export SMS_PROJECT_ROOT=/path/to/NextGen_SMS_live_cleaned   # folder with api/app.py
./run_tests.sh
```

This produces, in `reports/`:
- `report_<timestamp>.html` — full interactive report, every test + traceback
- `junit_<timestamp>.xml` — machine-readable results
- `SUMMARY_<timestamp>.txt` — **the one to attach for your HOD**: pass
  count, per-module breakdown, plain-English verdict

## Safety notes

- Every row this suite creates in the DB is tagged with a unique
  `zzqa<random>` prefix (roll numbers, usernames) and deleted in
  teardown — it will never touch or overwrite real student/faculty data.
- If MySQL isn't reachable, the suite exits immediately with a clear
  message instead of producing 55 confusing failures.
- If a test account's role has no subjects/semester configured yet,
  the attendance live-session tests skip cleanly (not a failure) rather
  than guessing IDs.

## What this suite still does NOT prove

- **OTP happy path** (real email delivery via `send-otp`/`verify-otp`) —
  only input validation is covered; actually sending/receiving an email
  is out of scope for an automated suite.
- **SMS gateway send** (`/api/dashboard/sms-test`) — only the RBAC
  boundary is tested. The actual send is skipped on purpose: it could
  hit a real Android SMS gateway or serial modem on some deployments.
- **PDF generation** (`GET /api/attendance/sessions/{id}/pdf`) — not
  covered in either phase; add if you want it.
- **Photo upload endpoints** (student/staff profile photos, student
  certificates) — file-upload plumbing isn't exercised; these routes
  call real image-processing code (`webapp/photo_upload.py`) that's
  easy to smoke-test manually but wasn't prioritized here.
- **create-account full lifecycle** — RBAC and validation are tested;
  the full create→delete round trip is left to manual testing (see
  `test_04_faculty_accounts.py`'s module docstring for why).

If any of these matter for your HOD presentation, tell Claude and a
Phase 3 file can cover them.
