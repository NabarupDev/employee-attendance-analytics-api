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

### Decision: Explicit UTC Storage with Strict Offset Enforcement
- In compliance with Requirement 7, the application never silently guesses or assumes a local timezone for naive strings.
- All incoming timestamps are validated by Pydantic:
  1. Must be timezone-aware (ISO 8601 with `Z` or explicit offset, e.g. `+05:30`). Naive strings are rejected with `422 Unprocessable Content`.
  2. Converted to UTC datetime objects immediately upon receipt (`astimezone(timezone.utc)`).
  3. Validated against clock skew: Timestamps exceeding 60 seconds into the future are rejected.
- Calendar date partitioning (`YYYY-MM-DD`) is strictly derived from the normalized UTC timestamp.

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

---

## 7. Correction Workflow & Audit Trail Design

### Decision: Dual-Collection Audit Pattern
Rather than modifying attendance records in-place without a historical trail:
1. **Request Collection (`corrections`):** Stores an immutable snapshot of the original attendance document (`original_record_snapshot`), the proposed punch sessions, justification reason, requesting actor, and reviewing actor.
2. **Attendance Collection Audit History (`attendance.audit_history`):** When approved by a manager, the attendance record is atomically updated (`is_corrected = True`), and a comprehensive audit log entry is appended recording `previous_punches`, `new_punches`, `previous_total_minutes`, `new_total_minutes`, `previous_status`, and `new_status`.
3. **Role Enforcement:** Reviews require `manager` or `admin` role (`X-Role` header). Self-approval is strictly prohibited (`reviewer_id == employee_id` raises `403 Forbidden`).
4. **Immutability:** Finalized correction requests (`APPROVED` / `REJECTED`) are immutable; subsequent mutation attempts are rejected with `400 Bad Request`.

---

## 8. Analytics Aggregation Pipelines

### Decision: Database-Engine Native Aggregations
All reporting queries are implemented as multi-stage MongoDB Aggregation Pipelines:
- **Stage 1 (`$match`):** Filter by date range and department early, utilizing compound indexes.
- **Stage 2 (`$group`):** Group by department or employee, summing working minutes and counting presence statuses using conditional operators (`$cond`).
- **Stage 3 (`$project`):** Shape the final output schema and compute hour representations.
- **Stage 4 (`$sort`):** Deterministic sorting by department or chronological date.

### Testing Compatibility Consideration:
While real MongoDB 4.2+ natively supports `$round` in projections, Python's in-memory mock library (`mongomock`) lacks the `$round` expression operator. To ensure 100% test reliability on both live MongoDB Atlas and CI mock runners, we compute sums and counts in the aggregation pipeline and perform 2-decimal rounding during Pydantic model serialization.

---

## 9. Testing Strategy

### Decision: Multi-Tiered Testing with Complete Database Isolation
1. **Hermetic Unit & Contract Tests (Default):** Mock database fixtures (`mongomock-motor`) isolate each test run in memory with pre-seeded employees, ensuring zero mutations touch live or production databases. By default, `pytest` executes 41 hermetic tests completely offline without external network or cluster dependencies.
2. **Live MongoDB Atlas Integration Test (On-Demand):** Test [`tests/test_live_atlas_integration.py`](file:///home/nabarup/Projects/employee-attendance-analytics-api/tests/test_live_atlas_integration.py) executes write, read, and aggregation pipeline operations directly against a live MongoDB Atlas cluster (configured via `MONGODB_URI` in `.env`), verifying real driver compatibility and index behavior. Executed via `pytest -m integration`.
3. **Zero Weakened Tests:** All 42 tests execute without skips or soft assertions.

---

## 10. Disclosed Limitations & Assumptions

1. **Authentication Scope:** Actor identity is provided via explicit HTTP headers (`X-Actor-ID` and `X-Role`). A production deployment would pair this with a JWT OAuth2 bearer token provider or corporate SSO.
2. **Overnight Shifts:** Shifts belong to the calendar date on which they commence.
3. **Employee Pre-Registration:** Attendance and correction endpoints enforce that the `employee_id` exists in the system (managed via `/api/v1/employees`).
