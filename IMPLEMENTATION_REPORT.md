# NextGen SMS — Reliability Implementation Report

Date: 2026-09-06

## Implemented

### Task A — Gateway credential encryption
- Added dedicated Fernet encryption using `SMS_CREDENTIAL_KEY`.
- New gateway writes encrypt `password` and `device_id`.
- API responses never return raw gateway secrets; device ID is masked.
- SMS transport decrypts secrets only at the transport boundary.
- Existing plaintext gateway credentials require one-time re-entry instead of silent migration.

### Task B — Post-cutoff absentee trigger
- Added `sms_absentee_cutoff_time`, default `10:15`, through the existing settings store.
- Comparison is strictly `created_at > cutoff`.
- Batch scope is the existing `hod_username + semester_id` data available in the repository.
- Current session must be the latest eligible post-cutoff session for that batch/day.
- Added DB-unique single-fire state in `sms_absentee_triggers` to prevent duplicate trigger rounds, including concurrent attempts.
- No timetable or period-number dependency was added.

### Task C — Per-row approval/rejection + auto-send
- Added `REJECTED` queue status and migration handling.
- Added scoped per-row Approve and Reject service/API operations.
- Rejected rows remain in `sms_queue` and are excluded from pending sending.
- Added per-gateway `auto_send`, default OFF.
- Auto-send marks eligible queued rows approved so the existing worker can claim them without manual approval.
- Added the auto-send control to the HOD account page.

### Task D — Message Type
- Added exact UI mode wording: `Message Type: ⦿ Absentee Alert ○ General Notice`.
- Added persisted per-HOD templates for Absentee Alert and General Notice.
- Absentee Alert continues through the cutoff/attendance path.
- General Notice queues one message per active student in the selected existing semester/batch, independently of attendance.
- General Notice uses the same queue, gateway, approval/rejection, and auto-send mechanics.

## Verification performed

- Python syntax/compile pass: PASS.
- New SMS overhaul regression tests: PASS — 8 tests.
- Existing offline security regression tests: PASS — 17 tests.
- Combined offline/security regression result: **25 passed**.
- Static scan confirms no raw `password`/`device_id` values are returned by gateway API serialization.
- Static scan found no timetable addition or `>=` cutoff drift.

## Environment limitations

- The full repository pytest suite cannot execute in this sandbox because the project requires a reachable MySQL instance at test startup. Baseline and final full-suite execution both stop before test collection with the project's MySQL connectivity/driver guard.
- The frontend production build cannot execute because npm dependencies are not installed and the sandbox cannot satisfy the package fetch in offline mode.

## Deliberate scope boundary

The repository has `users.hod_username` ownership but does **not** contain a batch-level faculty/delegate assignment mechanism. The task specification explicitly says not to invent a new delegation schema when that concept is absent and to flag the conflict. Therefore the implementation enforces the existing HOD + semester batch scope but does not fabricate a delegate-assignment model.
