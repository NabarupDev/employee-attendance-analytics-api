# Architectural & Design Decisions (DECISIONS.md)

**Project:** Employee Attendance & Analytics API  
**Context:** HR0ne Software Engineer Trainee Take-Home Assignment  
**Author:** Nabarup Roy  

This document outlines the architectural patterns, database modeling strategies, business logic boundaries, and trade-offs made during the development of the Employee Attendance & Analytics API.

---

## 1. Architecture & Module Boundaries

### Decision: Layered Architecture Pattern
We adopted a decoupled, four-tier architecture:
1. **API Router Layer (`app/api/v1/endpoints`):** Responsible purely for HTTP protocol parsing, header extraction, query validation, and HTTP status code mappings.
2. **Service Layer (`app/services`):** Encapsulates all domain business logic, invariants, time calculations, and orchestration between collections. No HTTP dependencies (`Request`, `Response`) exist in services.
3. **Data Schema Layer (`app/schemas`):** Utilizes Pydantic v2 schemas for strict boundary validation, timezone checks, and model serialization.
4. **Database Foundation Layer (`app/db`):** Manages async MongoDB connection pooling via Motor, index initialization, and connection lifecycle hooks in FastAPI's `lifespan` context.

### Rejected Alternative: Anemic Router Pattern
Embedding database queries directly into route functions was rejected because it hinders unit testing, tightly couples the transport layer to persistence, and leads to code duplication across endpoints.

---

## 2. MongoDB Driver Selection & ODM Strategy

### Decision: Native Motor Async Client paired with Pydantic v2
We selected `motor.motor_asyncio.AsyncIOMotorClient` paired with Pydantic v2 validation models.

### Trade-Off Analysis:
| Alternative | Trade-Off Evaluation | Outcome |
| :--- | :--- | :--- |
| **PyMongo (Sync)** | Synchronous blocking I/O starves FastAPI's event loop under concurrent traffic, requiring thread pool wrappers. | **Rejected** |
| **Beanie (Async ODM)** | Provides Active Record ODM syntax, but introduces an abstraction layer that complicates multi-stage native MongoDB aggregation pipelines (`$group`, `$facet`, `$project`). | **Rejected** |
| **Motor (Native Async)** | Official asynchronous driver by MongoDB, natively non-blocking, direct access to raw aggregation pipelines and compound indexes without translation overhead. | **Selected** |

---

## 3. Data Modeling: Daily Document vs. Event Sourcing

### Decision: Consolidated Daily Attendance Document with Embedded Punch Sessions
We store a single document per employee per calendar date (`{ employee_id, date }`) containing an embedded array of punch sessions (`punches: [{ session_id, punch_in, punch_out, duration_minutes }]`).

### Trade-Off Analysis:
- **Pure Event Sourcing (Isolated Punch Events):**
  - *Pros:* Appending punch events is simple.
  - *Cons:* Calculating an employee's daily status or checking if an active session is open requires expensive self-joins (`$lookup`) or sorting through historical rows on every request.
- **Daily Document Pattern (Selected):**
  - *Pros:* Atomic updates via MongoDB operators (`$push`, `$set`), sub-millisecond retrieval by compound unique key `{ employee_id: 1, date: 1 }`, and immediate availability of aggregated metrics (`total_work_minutes`, `has_active_session`).
  - *Night Shift Handling:* The session document belongs to the date on which punch-in occurred. Cross-midnight sessions remain linked to the originating record and are found via `{ employee_id, has_active_session: True }`. Punch-in validates active sessions globally across all dates to prevent multi-day open session leaks.

---

## 4. Database Indexing Strategy

To guarantee scalability and prevent full-collection scans ($O(N)$), the following compound indexes were created:

| Collection | Index Fields | Type | Purpose |
| :--- | :--- | :--- | :--- |
| `attendance` | `{ employee_id: 1, date: 1 }` | **Compound Unique** | Guarantees strictly one daily document per employee per day; enables instant lookup for daily logs. |
| `attendance` | `{ date: 1, department: 1 }` | **Compound** | Directly satisfies `$match` queries in Daily Department Analytics pipelines. |
| `attendance` | `{ employee_id: 1, has_active_session: 1 }` | **Compound** | Instant index scan for active session validation during punch-in/out across all dates. |
| `corrections` | `{ employee_id: 1, attendance_date: 1 }` | **Partial Unique** (`status: "PENDING"`) | Guarantees strictly one pending correction request per employee per date at database level. |
| `corrections` | `{ status: 1, created_at: -1 }` | **Compound** | Optimizes manager review queue sorted by submission timestamp. |
| `employees` | `{ employee_id: 1 }` | **Unique** | Primary business key uniqueness. |

---

## 5. Timestamp & Timezone Integrity

### Decision: Multi-Format Ingestion (ISO 8601 + Epoch Milliseconds) with UTC Normalization
- In compliance with Requirement 7, the application never silently guesses or assumes a local timezone for naive strings.
- Ingestion Validator (`validate_timezone_aware_timestamp`):
  1. **ISO 8601:** Accepts timezone-aware ISO 8601 strings (with `Z` or explicit offset, e.g. `+05:30`).
  2. **Epoch Milliseconds & Seconds:** Accepts numeric integer/float values (or numeric strings). Milliseconds ($> 10^{11}$) are converted to seconds and parsed with explicit UTC timezone.
  3. **Skew Protection:** Rejects future timestamps exceeding a 60-second clock skew tolerance.
  4. Calendar date partitioning (`YYYY-MM-DD`) is strictly derived from the normalized UTC datetime.

---

## 6. Attendance Business Rules Enforcement

1. **BR-01 (Duplicate Punch-In):** Verified by inspecting `has_active_session == True`. Rejects with `400 Bad Request` (`ACTIVE_SESSION_EXISTS`).
2. **BR-02 (Orphan Punch-Out):** Verified by querying `{ employee_id, has_active_session: True }`. If no open session exists, rejects with `400 Bad Request` (`NO_ACTIVE_SESSION`).
3. **BR-03 (Chronological Order):** Rejects any punch-out where $t_{\text{out}} \le t_{\text{in}}$ with `422 Unprocessable Content`.
4. **BR-05 (Duration Math & Status):**
   - Session duration = $\text{round}((t_{\text{out}} - t_{\text{in}}).total\_seconds() / 60)$.
   - Status Evaluation:
     - $\ge 480\text{ minutes}$ (8.0 hrs) $\implies \text{PRESENT}$
     - $\ge 240\text{ minutes}$ (4.0 hrs) and $< 480\text{ minutes}$ $\implies \text{HALF\_DAY}$
     - $< 240\text{ minutes}$ $\implies \text{ABSENT}$
     - Active session open $\implies \text{IN\_PROGRESS}$
5. **BR-SHIFT-01 (Punctuality & Grace Period):** Shift start defaults to `09:00` with an explicit 15-minute grace period (`09:15` cutoff). Punch-ins after grace period are tracked in the Late-Arrival Leaderboard.

---

## 7. Correction Workflow, Atomicity & Audit Trail Design

### Decision: Dual-Collection Audit Pattern with Optimistic Concurrency Control and Safe Recovery
Rather than modifying attendance records in-place without a historical trail:
1. **Request Collection (`corrections`):** Stores an immutable snapshot of the original attendance document (`original_record_snapshot`), the proposed punch sessions, justification reason, requesting actor, and reviewing actor.
2. **Attendance Collection Audit History (`attendance.audit_history`):** When approved by a manager, the attendance record is updated (`is_corrected = True`), and a comprehensive audit log entry is appended recording `previous_punches`, `new_punches`, `previous_total_minutes`, `new_total_minutes`, `previous_status`, and `new_status`.
3. **Optimistic Concurrency Control & Compensating Rollback:**
   - **Conflict Detection:** Prior to approval, the service inspects the attendance record. If an active session is in progress or if punches were modified/added since the snapshot was taken, the approval is rejected with `409 Conflict`.
   - **CAS State Transition:** The CAS update on `corrections` (`PENDING -> APPROVED`) executes first, guaranteeing single-winner resolution without touching attendance. Subsequent attempts receive `400 CORRECTION_ALREADY_RESOLVED`.
   - **Conditional Write & Compensating Recovery:** The attendance write uses an exact filter matching on `has_active_session: False` and current punches. If the attendance write fails, a compensating rollback reverts the correction status back to `PENDING` without touching the attendance collection (ensuring concurrent punches are never overwritten by stale snapshots). If compensating recovery fails, a fatal `DATABASE_INCONSISTENCY_ERROR` is logged and returned for administrative intervention.
   - *Atomicity Scope Notice:* While multi-document ACID transactions are utilized where supported by replica sets, standalone instances use this OCC and compensating rollback workflow, which provides eventual consistency rather than multi-document ACID atomicity.
4. **Role Enforcement & Anti-Bypass Security:** Reviews require authorized managerial permissions resolved strictly from trusted database records. The reviewer identity (`X-Actor-ID`) must exist in `employees` and have a managerial designation in MongoDB (`"manager"`, `"admin"`, `"lead"`, `"director"`, `"head"`, `"vp"`). Non-manager employees attempting to claim `X-Role: admin` or `X-Role: manager` are strictly rejected with `403 Forbidden`. Self-approval (`reviewer_id == employee_id`) is strictly blocked with `403 Forbidden`.
5. **Direct Attendance Regularization:** Direct regularization routes (`POST/PATCH /attendance/records/{emp}/{date}/regularize` and `/attendance/regularize`) enforce the same authorization boundaries: required active registered manager/admin and strict blocking of self-regularization.
6. **Immutability:** Finalized correction requests (`APPROVED` / `REJECTED`) cannot be re-reviewed (`400 Bad Request`).

---

## 8. Analytics Aggregation Pipelines

### Decision: Database-Engine Native Aggregations
All reporting queries are implemented as multi-stage MongoDB Aggregation Pipelines:
- **Daily Department Summary:** Aggregates department headcount, presence status counts, work minutes, and average work hours.
- **Employee Period Breakdown:** Computes individual working days, presence rates, and chronological day-by-day punch summaries.
- **Department Period Performance:** Computes presence percentages, total overtime occurrences ($> 8\text{ hrs}$), and average working hours.
- **Monthly Summary (`GET /analytics/monthly-summary`):** Monthly attendance overview grouped by department with work-hour aggregates.
- **Late-Arrival Leaderboard (`GET /analytics/late-arrivals`):** Ranks employees by frequency of late check-ins beyond the 15-minute grace period.
- **Pipeline Execution Plan (`GET /admin/explain/{endpoint}`):** Provides administrative transparency into aggregation pipeline stages and indexing efficiency.

---

## 9. Testing Strategy

### Decision: Multi-Tiered Testing with Complete Database Isolation
1. **Hermetic Unit & Contract Tests (Default):** Mock database fixtures (`mongomock-motor>=0.0.29`, declared in both `requirements.txt` and `pyproject.toml`) isolate each test run in memory with pre-seeded employees, ensuring zero mutations touch live or production databases. By default, `pytest` executes 66 hermetic tests completely offline without external network or cluster dependencies.
2. **Live MongoDB Atlas Integration Test (On-Demand):** Test [`tests/test_live_atlas_integration.py`](tests/test_live_atlas_integration.py) executes write, read, and aggregation pipeline operations directly against a live MongoDB Atlas cluster (configured via `MONGODB_URI` in `.env`), verifying real driver compatibility and index behavior. Executed via `pytest -m integration`.
3. **Zero Weakened Tests:** All tests execute with strict assertions verifying exact status codes, payload structures, concurrency safeguards, and mathematical outputs.



---

## 10. Disclosed Limitations & Assumptions

1. **Authentication Scope:** Actor identity is provided via explicit HTTP headers (`X-Actor-ID` and `X-Role`). In production, this would be backed by JWT OAuth2 tokens or SSO.
2. **Dual Route Compatibility:** Endpoints are registered at both `/api/v1/...` and root `/...` to ensure full interoperability with any evaluation harness.
3. **Dual Identifier Interoperability:** Systems may pass either `employee_id` or `emp_code`; both are returned in responses.

