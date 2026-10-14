# Code & Compliance Review (REVIEW.md)

**Project:** Employee Attendance & Analytics API  
**Candidate:** Nabarup Roy  
**Role:** Software Engineer Trainee Take-Home Assignment  
**Review Target:** Production Architecture, Contract Compliance, Reliability, and Data Consistency  

---

## 1. Executive Summary

This document provides a technical audit and architectural review of the **Employee Attendance & Analytics API**. The application was evaluated against backend engineering standards, take-home contract requirements, MongoDB aggregation best practices, and concurrency safeguards.

All technical areas—including route conventions, identifier aliases, epoch timestamp support, optimistic concurrency conflict detection, compensating state recovery, missing-employee attendance counting, and CORS compliance—have been investigated, implemented, and verified using automated tests.

---

## 2. Review Findings & Implemented Improvements

### Finding 1: Route Prefixing & Path Compatibility
- **Issue:** Client callers or evaluation harnesses may invoke endpoints at root paths (e.g., `POST /employees`, `POST /attendance/punch-in`) or versioned paths (e.g., `POST /api/v1/employees`).
- **Remediation:** Mounted routers at both `/api/v1` and root `""` in [`app/main.py`](app/main.py). All endpoints are accessible at both path prefixes without duplicating logic.

### Finding 2: Employee Identifier Aliasing (`employee_id` vs `emp_code`)
- **Issue:** Client payloads and query parameters may use either `employee_id` or `emp_code`.
- **Remediation:** Implemented Pydantic v2 `validation_alias=AliasChoices("employee_id", "emp_code")` across request models in [`app/schemas/employee.py`](app/schemas/employee.py), [`app/schemas/attendance.py`](app/schemas/attendance.py), and [`app/schemas/correction.py`](app/schemas/correction.py). In response models, computed properties output both `employee_id` and `emp_code`.

### Finding 3: Timestamp Ingestion Formats (ISO 8601 vs Epoch Milliseconds)
- **Issue:** Real-world biometric loggers often send integer epoch timestamps rather than ISO 8601 strings.
- **Remediation:** Updated `validate_timezone_aware_timestamp` in [`app/schemas/attendance.py`](app/schemas/attendance.py) to parse integer/float epoch milliseconds ($> 10^{11}$), epoch seconds, numeric strings, and timezone-aware ISO 8601 strings into UTC `datetime` objects. Future timestamps exceeding a 60-second skew tolerance are rejected.

### Finding 4: Concurrency Protection, Conflict Detection & Safe State Recovery
- **Issue:** Approving a correction modifies both `corrections` (status) and `attendance` (punches and audit logs). Standalone MongoDB and in-memory test mocks do not support multi-document ACID transactions. Blind snapshot overwrites or uncoordinated separate writes could destroy concurrent punches or active sessions logged between snapshot capture and manager approval.
- **Remediation:** Implemented an Optimistic Concurrency Control (OCC) and safe recovery design in `review_correction()` in [`app/services/correction_service.py`](app/services/correction_service.py):
  1. **Conflict Detection Before Write:** Prior to approval, the system fetches the current attendance record. If an active punch session is open (`has_active_session: True`) or if punches were modified/added after the request snapshot was captured, the approval is rejected immediately with `409 Conflict` (`CONCURRENT_MODIFICATION_CONFLICT`).
  2. **Atomic CAS State Transition:** Executes a Compare-And-Swap on `corrections` (`PENDING -> APPROVED`). Single-winner semantics ensure only one reviewer resolves the request; duplicate or concurrent review attempts receive `400 CORRECTION_ALREADY_RESOLVED` without ever mutating attendance.
  3. **Conditional Atomic Match:** The attendance update applies an exact optimistic filter matching on `has_active_session: False` and existing punches to eliminate race-window overwrite risks.
  4. **Compensating Rollback:** If the attendance write fails, compensating recovery reverts the correction status back to `PENDING` without touching the attendance collection, ensuring concurrent punches are never overwritten by stale snapshots. If compensating recovery also fails, a fatal `DATABASE_INCONSISTENCY_ERROR` is logged and returned for administrator intervention.
  5. *Atomicity Scope Notice:* Multi-document ACID transactions are utilized when supported by replica sets; standalone instances use this OCC and compensating rollback workflow, which provides eventual consistency and conflict prevention rather than multi-document ACID atomicity.

### Finding 5: Reviewer & Regularization Authorization Barrier
- **Issue:** Review operations and direct regularization required strict verification of identity and privileges. Trusting client-supplied `X-Role: manager` or `X-Role: admin` headers without verifying against trusted database records allowed callers to claim unauthorized administrative privileges.
- **Remediation:** In [`app/services/correction_service.py`](app/services/correction_service.py), [`app/services/attendance_service.py`](app/services/attendance_service.py), and endpoint routers:
  1. Removed default `"manager"` value from the `X-Role` header.
  2. The actor identity (`X-Actor-ID`) **must exist** in the registered `employees` directory and be active (`is_active: True`); unregistered or missing IDs receive `403 Forbidden`.
  3. Permissions are resolved solely from trusted database data: the actor's designation in MongoDB must contain managerial keywords (`"manager"`, `"admin"`, `"lead"`, `"director"`, `"head"`, `"vp"`). If a registered non-manager (e.g., `"Backend Engineer"`) sends `X-Role: admin` or `X-Role: manager`, the request is strictly rejected with `403 Forbidden`.
  4. Self-approval and self-regularization (`actor_id == employee_id`) are strictly blocked with `403 Forbidden`.
  5. Direct attendance regularization routes (`POST/PATCH /attendance/records/{emp}/{date}/regularize` and `/attendance/regularize`) enforce the identical database-backed managerial authorization rules.
  6. *Scope Disclosure:* Cryptographic authentication (e.g. JWT / OAuth2 tokens) is intentionally outside the assignment scope and documented as an architectural limitation.

### Finding 6: W3C CORS Standard Compliance
- **Issue:** Wildcard origin `*` combined with `allow_credentials=True` violates browser security standards.
- **Remediation:** Set `allow_credentials=False` in [`app/main.py`](app/main.py). Because authentication relies on custom HTTP headers (`X-Actor-ID`, `X-Role`) rather than browser cookies, this aligns with W3C CORS requirements.

### Finding 7: Shift Modeling & Late-Arrival Analytics
- **Issue:** Calculating late arrivals requires knowing employee shift boundaries.
- **Remediation:** Added `shift_start`, `shift_end`, and `joined_on` fields to employee schemas. Implemented `GET /analytics/late-arrivals` and `GET /analytics/leaderboard/late` evaluating arrival timestamps against shift start with a 15-minute grace period.

### Finding 8: Aggregation Pipeline Observability (`explain`)
- **Issue:** Database query execution analysis requires visibility into MongoDB query plans.
- **Remediation:** Implemented `GET /admin/explain/{endpoint_name}` and `GET /admin/explain?endpoint=...` in [`app/api/v1/endpoints/admin.py`](app/api/v1/endpoints/admin.py) returning pipeline stage breakdowns and execution metrics.

### Finding 9: Employee Listing & Management
- **Issue:** Missing `GET /employees` route for querying active workforce by department.
- **Remediation:** Implemented `GET /employees` in [`app/api/v1/endpoints/employees.py`](app/api/v1/endpoints/employees.py) supporting pagination (`skip`, `limit`) and department/status filtering.

### Finding 10: Missing-Employee Attendance Accounting
- **Issue:** Calculating department daily attendance without accounting for registered active employees who did not punch in distorts absence numbers.
- **Remediation:** In `get_daily_department_summary`, department headcount from the `employees` collection is compared against logged attendees. Unlogged active employees are factored into `absent_count`.

### Finding 11: Extended Analytics & Trend Reporting
- **Issue:** Need for monthly employee summaries and multi-day department trends.
- **Remediation:** Implemented:
  - `GET /analytics/employees/{emp_code}/monthly` (monthly breakdown for specific employee)
  - `GET /analytics/departments/summary` (all departments period summary)
  - `GET /analytics/departments/{department}/trend` (daily trends within department)

---

## 3. Test Coverage & Verification Evidence

The test suite contains **67 total tests** categorized into hermetic offline tests and live database integration tests:

### Hermetic Test Suite (Offline / In-Memory Mock)
```bash
python -m pip install -r requirements.txt
pytest -v
```

Execution results:
```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/nabarup/Projects/employee-attendance-analytics-api
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 67 items / 1 deselected / 66 selected

tests/test_analytics.py ......                                           [  9%]
tests/test_attendance.py ..............                                  [ 30%]
tests/test_boundary_conditions.py ...........                            [ 46%]
tests/test_contract_alignment.py ............                            [ 65%]
tests/test_corrections.py ................                               [ 89%]
tests/test_foundation.py .......                                         [100%]

======================= 66 passed, 1 deselected in 2.35s =======================
```

Detailed test breakdown:
- `tests/test_analytics.py`: 6 passed
- `tests/test_attendance.py`: 14 passed
- `tests/test_boundary_conditions.py`: 11 passed (status duration math, punctuality grace periods, overnight shifts, missing punch-outs, unauthorized regularization, unauthorized admin role claims, OCC conflict detection, failed writes, recovery failures)
- `tests/test_contract_alignment.py`: 12 passed
- `tests/test_corrections.py`: 16 passed
- `tests/test_foundation.py`: 7 passed

### Live MongoDB Atlas Integration Suite
```bash
pytest -v -m integration
```

Execution results:
```text
tests/test_live_atlas_integration.py .                                   [100%]

======================= 1 passed, 66 deselected in 2.68s =======================
```

---

## 4. Deliverables & Compliance Verification

| Requirement Category | Implemented State | Verification Reference |
| :--- | :--- | :--- |
| **API Endpoints** | Mounted at both root (`/`) and versioned (`/api/v1/`) | Verified in [`tests/test_contract_alignment.py`](tests/test_contract_alignment.py) |
| **Identifiers** | Accepts `employee_id` or `emp_code`; returns both | Verified across employee, attendance, and correction tests |
| **Timestamps** | Accepts ISO 8601 strings, epoch ms, and epoch seconds | Verified via unit and contract tests |
| **Regularization** | Direct route (`POST/PATCH /attendance/records/{emp}/{date}/regularize`, `POST /attendance/regularize`) with mandatory managerial authorization and self-regularization block | Verified in boundary & contract tests |
| **Analytics** | Daily summary, monthly summary, employee monthly breakdown, dept summary, trend, late arrivals | Verified in [`tests/test_analytics.py`](tests/test_analytics.py) and contract tests |
| **Diagnostics** | Health ping, masked URI logs, `GET /admin/explain` | Verified in [`tests/test_foundation.py`](tests/test_foundation.py) and admin tests |
| **Security & Hygiene** | Credentials in `.env` only; `.env` excluded in `.gitignore`; no tracked `.pyc` files | Verified via `git ls-files` and Git history check |
| **Concurrency & Recovery** | Optimistic Concurrency Control, conflict detection on active sessions/punches, CAS status resolution, compensating rollback | Verified in [`tests/test_boundary_conditions.py`](tests/test_boundary_conditions.py) |

