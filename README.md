# Employee Attendance & Analytics API

> High-performance, asynchronous REST API for employee attendance tracking, business-rule-governed corrections, and aggregation-driven analytics built with **Python 3.11+**, **FastAPI**, and **MongoDB**.

Developed for the **HR0ne Software Engineer Trainee Take-Home Assignment**.

---

## 1. Project Overview & Scope

The **Employee Attendance & Analytics API** provides an enterprise-ready backend service designed to handle core workforce management operations:
- **Attendance Tracking:** Real-time punch-in and punch-out recording with automatic session duration calculation and daily status transitions (`PRESENT`, `HALF_DAY`, `ABSENT`).
- **Attendance Corrections & Audit Trail:** Structured workflow allowing employees to request retroactive attendance corrections with mandatory justification reasons. Corrections undergo manager/admin review and maintain an immutable before-and-after audit history.
- **High-Performance Analytics:** Native **MongoDB Aggregation Pipelines** (`$match`, `$group`, `$project`, `$sort`) that compute departmental summaries, employee work-hour aggregates, and overtime statistics directly inside the database engine without memory bloat.
- **Enterprise Diagnostics & Clean Lifecycle:** Async connection pooling via `motor.motor_asyncio`, non-sensitive credential masking in logs, automated compound index creation, and RFC 7807 structured error responses.

---

## 2. Technology Stack

- **Language:** Python 3.11+ (verified on Python 3.14.4)
- **Web Framework:** FastAPI `0.110.0+`
- **ASGI Server:** Uvicorn `0.28.0+`
- **Database Driver:** Motor `3.3.0+` (Official Asynchronous MongoDB Driver)
- **Data Validation & Settings:** Pydantic v2 `2.6.0+` & Pydantic-Settings `2.2.0+`
- **Testing & Quality:** Pytest `8.0.0+`, Pytest-Asyncio `0.23.0+`, HTTPX `0.27.0+`, Mongomock-Motor `0.0.29+`

---

## 3. Prerequisites

- **Python:** 3.11 or newer (`python3 --version`)
- **MongoDB:** A local MongoDB instance (`mongodb://localhost:27017`) **or** a cloud MongoDB Atlas cluster connection URI.

---

## 4. Installation & Environment Setup

### Step 1: Clone or Navigate to the Repository
```bash
cd employee-attendance-analytics-api
```

### Step 2: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy the sanitized environment template:
```bash
cp .env.example .env
```

Edit `.env` with your preferred configuration:
```env
# Application Configuration
PROJECT_NAME="Employee Attendance & Analytics API"
ENVIRONMENT="development"
DEBUG=true
HOST="0.0.0.0"
PORT=8000

# MongoDB Configuration (Local or Cloud Atlas)
# Example for local MongoDB:
# MONGODB_URI="mongodb://localhost:27017"
# Example for MongoDB Atlas:
MONGODB_URI="mongodb+srv://<username>:<password>@<cluster-url>/?retryWrites=true&w=majority"
MONGODB_DB_NAME="attendance_analytics_db"
MONGODB_MIN_POOL_SIZE=10
MONGODB_MAX_POOL_SIZE=50
MONGODB_SERVER_SELECTION_TIMEOUT_MS=5000
```

> **Security Note:** `.env` is strictly excluded from version control in `.gitignore`. Real credentials are never committed.

---

## 5. Running the Application

Start the development server with live reload:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Once started:
- **Interactive Swagger Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check Endpoint:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 6. Running Tests

The test suite includes 42 comprehensive unit, contract, and integration tests covering business rules, isolated mock databases, and live MongoDB Atlas integration:

```bash
# Run all hermetic offline tests (41 tests, isolated in-memory)
pytest -v

# Run tests with short output
pytest -q

# Run live MongoDB Atlas integration test (requires live database connection)
pytest -v -m integration

# Run the complete test suite including live integration
pytest -v -m ""
```

---

## 7. API Specification & Representative Examples

### 7.1 Employee Onboarding
#### `POST /api/v1/employees`
**Request:**
```json
{
  "employee_id": "EMP-1001",
  "name": "Alice Walker",
  "email": "alice.walker@hr0ne.internal",
  "department": "Engineering",
  "designation": "Backend Engineer"
}
```
**Response (`201 Created`):**
```json
{
  "success": true,
  "message": "Employee registered successfully.",
  "data": {
    "employee_id": "EMP-1001",
    "name": "Alice Walker",
    "email": "alice.walker@hr0ne.internal",
    "department": "Engineering",
    "designation": "Backend Engineer",
    "is_active": true
  }
}
```

---

### 7.2 Attendance Operations

#### `POST /api/v1/attendance/punch-in`
**Request:**
```json
{
  "employee_id": "EMP-1001",
  "timestamp": "2026-10-10T09:00:00Z"
}
```
**Response (`201 Created`):**
```json
{
  "success": true,
  "message": "Punch-in recorded successfully.",
  "data": {
    "id": "6accc81a433fbf232e652aa8",
    "employee_id": "EMP-1001",
    "department": "Engineering",
    "date": "2026-10-10",
    "punches": [
      {
        "session_id": "06fabaee-1a67-481a-873e-0eba7a83ccdc",
        "punch_in": "2026-10-10T09:00:00Z",
        "punch_out": null,
        "duration_minutes": null
      }
    ],
    "has_active_session": true,
    "total_work_minutes": 0,
    "total_work_hours": 0.0,
    "status": "IN_PROGRESS",
    "is_corrected": false
  }
}
```

#### `POST /api/v1/attendance/punch-out`
**Request:**
```json
{
  "employee_id": "EMP-1001",
  "timestamp": "2026-10-10T17:30:00Z"
}
```
**Response (`200 OK`):**
```json
{
  "success": true,
  "message": "Punch-out recorded successfully.",
  "data": {
    "id": "6accc81a433fbf232e652aa8",
    "employee_id": "EMP-1001",
    "department": "Engineering",
    "date": "2026-10-10",
    "punches": [
      {
        "session_id": "06fabaee-1a67-481a-873e-0eba7a83ccdc",
        "punch_in": "2026-10-10T09:00:00Z",
        "punch_out": "2026-10-10T17:30:00Z",
        "duration_minutes": 510
      }
    ],
    "has_active_session": false,
    "total_work_minutes": 510,
    "total_work_hours": 8.5,
    "status": "PRESENT",
    "is_corrected": false
  }
}
```

---

### 7.3 Attendance Corrections & Audit Trail

#### `POST /api/v1/corrections/request`
**Request:**
```json
{
  "employee_id": "EMP-1001",
  "attendance_date": "2026-10-05",
  "proposed_punches": [
    {
      "punch_in": "2026-10-05T09:00:00Z",
      "punch_out": "2026-10-05T17:30:00Z"
    }
  ],
  "reason": "Main gate turnstile was offline during morning entry."
}
```
**Response (`201 Created`):**
```json
{
  "success": true,
  "message": "Attendance correction request submitted successfully.",
  "data": {
    "id": "6accc924376fb1b94b29bb88",
    "employee_id": "EMP-1001",
    "attendance_date": "2026-10-05",
    "status": "PENDING",
    "reason": "Main gate turnstile was offline during morning entry.",
    "proposed_punches": [
      {
        "punch_in": "2026-10-05T09:00:00Z",
        "punch_out": "2026-10-05T17:30:00Z"
      }
    ]
  }
}
```

#### `PATCH /api/v1/corrections/{id}/status`
**Headers:**
- `X-Actor-ID`: `MGR-5001`
- `X-Role`: `manager`

**Request:**
```json
{
  "status": "APPROVED",
  "remarks": "Verified manual security ledger."
}
```
**Response (`200 OK`):**
```json
{
  "success": true,
  "message": "Correction request successfully approved.",
  "data": {
    "id": "6accc924376fb1b94b29bb88",
    "status": "APPROVED",
    "reviewed_by": "MGR-5001",
    "review_remarks": "Verified manual security ledger."
  }
}
```

---

### 7.4 Attendance Analytics (MongoDB Aggregation Pipelines)

#### `GET /api/v1/analytics/daily-summary?date=2026-10-10`
**Response (`200 OK`):**
```json
{
  "success": true,
  "message": "Generated daily attendance summary for 2026-10-10.",
  "data": [
    {
      "date": "2026-10-10",
      "department": "Engineering",
      "total_employees_logged": 2,
      "present_count": 1,
      "half_day_count": 0,
      "absent_count": 0,
      "in_progress_count": 1,
      "corrected_records_count": 0,
      "total_work_minutes": 510,
      "total_work_hours": 8.5,
      "avg_work_hours": 4.25
    }
  ]
}
```

#### `GET /api/v1/analytics/employee/EMP-1001?start_date=2026-10-01&end_date=2026-10-03`
**Response (`200 OK`):**
```json
{
  "success": true,
  "message": "Generated attendance summary for employee 'EMP-1001' (2026-10-01 to 2026-10-03).",
  "data": {
    "employee_id": "EMP-1001",
    "start_date": "2026-10-01",
    "end_date": "2026-10-03",
    "total_days_logged": 3,
    "present_days": 2,
    "half_days": 1,
    "absent_days": 0,
    "in_progress_days": 0,
    "corrected_days_count": 1,
    "total_work_minutes": 1260,
    "total_work_hours": 21.0,
    "avg_daily_work_hours": 7.0,
    "daily_breakdown": [
      {
        "date": "2026-10-01",
        "status": "PRESENT",
        "total_work_minutes": 480,
        "total_work_hours": 8.0,
        "is_corrected": false
      }
    ]
  }
}
```

#### `GET /api/v1/analytics/department-summary?department=Engineering&start_date=2026-10-01&end_date=2026-10-10`
**Response (`200 OK`):**
```json
{
  "success": true,
  "message": "Generated performance summary for department 'Engineering' (2026-10-01 to 2026-10-10).",
  "data": {
    "department": "Engineering",
    "start_date": "2026-10-01",
    "end_date": "2026-10-10",
    "total_attendance_records": 5,
    "present_count": 3,
    "half_day_count": 1,
    "absent_count": 0,
    "corrected_records_count": 1,
    "overtime_records_count": 2,
    "total_work_minutes": 1770,
    "total_work_hours": 29.5,
    "avg_hours_per_record": 5.9,
    "present_rate_percent": 60.0
  }
}
```

---

## 8. Business Rules & Validation

| Rule | Description | Behavior |
| :--- | :--- | :--- |
| **BR-01** | Duplicate Punch-In | Rejects punch-in if `has_active_session == True` (`400 Bad Request`, `ACTIVE_SESSION_EXISTS`). |
| **BR-02** | Orphan Punch-Out | Rejects punch-out if no active punch session exists (`400 Bad Request`, `NO_ACTIVE_SESSION`). |
| **BR-03** | Chronological Ordering | Rejects punch-out where $t_{\text{out}} \le t_{\text{in}}$ (`422 Unprocessable Content`, `INVALID_TIMESTAMP`). |
| **BR-04** | Future Timestamps | Rejects future timestamps exceeding 60-second clock skew (`422 Unprocessable Content`). |
| **BR-05** | Daily Work Status | $\ge 480\text{m} \implies \text{PRESENT}$; $\ge 240\text{m} \implies \text{HALF\_DAY}$; $< 240\text{m} \implies \text{ABSENT}$. |
| **BR-COR-01** | Mandatory Reason | Rejects correction requests where justification is $< 10$ characters (`422 Unprocessable Content`). |
| **BR-COR-02** | Non-Overlapping | Rejects correction requests with overlapping proposed punch intervals (`422 Unprocessable Content`). |
| **BR-COR-03** | Retroactive Limit | Rejects corrections for dates older than 30 days (`400 Bad Request`, `RETROACTIVE_LIMIT_EXCEEDED`). |
| **BR-COR-04** | Duplicate Pending | Rejects duplicate pending corrections for the same employee and date (`409 Conflict`). |
| **BR-COR-05** | Role Authorization | Review requires `manager` or `admin` role (`403 Forbidden`). Employees cannot self-approve (`403 Forbidden`). |
| **BR-COR-06** | State Immutability | Finalized corrections (`APPROVED` / `REJECTED`) cannot be modified (`400 Bad Request`). |

---

## 9. Known Limitations & Disclosed Boundaries

1. **Authentication Strategy:** In accordance with the assignment's instructions not to fabricate complex OAuth2/JWT providers when unspecified, actor identification is enforced via explicit HTTP headers (`X-Actor-ID` and `X-Role`).
2. **Night Shifts & Date Partitioning:** Attendance sessions belong to the calendar date on which the punch-in occurred. Cross-midnight shifts are supported and counted toward the starting day.
# employee-attendance-analytics-api
