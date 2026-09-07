# Role Hierarchy & Audit Implementation Record

## Implemented

- ADMIN and HOD are no longer treated as interchangeable on Faculty/account management.
- HOD Faculty API is restricted to FACULTY accounts whose `hod_username` matches the authenticated HOD.
- HOD Faculty data and faculty-by-subject data are scope-filtered.
- HOD cannot update ADMIN role permissions.
- HOD cannot read or update ADMIN individual permissions.
- ADMIN role permissions are not exposed through the HOD permissions endpoint.
- HOD cannot create ADMIN/HOD accounts; ADMIN can create subordinate management accounts.
- Account status and deletion use the target account's real `role`, not a special username such as `admin`.
- ADMIN may delete HOD/FACULTY/STUDENT targets (except the currently authenticated ADMIN account itself).
- HOD may only mutate accounts in its own subordinate scope.
- Student password reset through the Faculty management API is now scope-checked as well.
- `audit_logs.actor_role` was added with an idempotent migration and current-user backfill for existing rows.
- Audit history is no longer dependent on an INNER JOIN to an existing user row, so deleting a user does not erase the audit record from the audit table/view.
- Audit endpoint now supports server-side actor-role and activity filtering.
- HODs cannot request ADMIN audit entries.
- ADMINs have a distinct Admin Activity view capable of filtering by administrator username.
- Operational People Activity can be filtered to Students, Faculty, or HOD.
- Audit default is Actions only; Login & Logout and All activity are available without deleting underlying records.
- Human-readable audit descriptions are generated centrally in `sms_app/services/audit_service.py`.
- Frontend Audit page no longer presents raw action/entity codes as the primary content.
- Faculty UI no longer offers HOD/ADMIN creation choices to HOD users.

## Verification

- Python compilation of all changed Python files: PASS.
- Existing offline/security + SMS regression tests: 25 PASS.
- New database-backed hierarchy/audit tests are included but require the project's configured MySQL test environment.
- Frontend dependency/type-check remains environment-blocked because React/npm dependencies are not installed in this sandbox; no existing dependency files were modified to hide that limitation.

## Known boundary

The current repository has HOD ownership via `users.hod_username`, but it does not contain a full batch-level faculty-delegation assignment model. This pass therefore does not invent one.
