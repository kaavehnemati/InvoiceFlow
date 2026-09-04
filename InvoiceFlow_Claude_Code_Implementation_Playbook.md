# InvoiceFlow — FastAPI + AWS Implementation Playbook for Claude Code

> **Purpose:** A phase-by-phase implementation plan for building a real-world invoice intake, validation, and processing platform while learning FastAPI, backend architecture, Docker, AWS, messaging, distributed systems, and Infrastructure as Code.
>
> **Primary rule:** Do **not** skip phases and do **not** introduce abstractions, AWS services, or architectural layers before the phase that requires them.

---

# 1. Project Overview

## 1.1 What are we building?

**InvoiceFlow** is a backend platform that helps companies ingest, validate, process, and track invoices.

The system evolves gradually:

```text
Manual JSON invoice
        ↓
Structured validation
        ↓
PostgreSQL persistence
        ↓
Excel invoice import
        ↓
File storage
        ↓
Asynchronous processing
        ↓
PDF / image invoice intake
        ↓
OCR / field extraction
        ↓
Bulk processing
        ↓
Production AWS deployment
```

The final platform should be able to:

- Accept invoices through REST endpoints.
- Validate invoice fields and business rules.
- Import standardized Excel files.
- Store uploaded files.
- Track processing jobs.
- Process imports asynchronously.
- Publish domain events.
- Handle retries and failures.
- Accept PDF/image invoices.
- Extract invoice information from unstructured documents.
- Process large historical imports.
- Run in containers on AWS.
- Scale behind a load balancer.
- Provision infrastructure with Terraform.
- Deploy through CI/CD.
- Provide an alternative Kubernetes deployment.
- Document a hybrid AWS Outposts architecture.

---

# 2. Business Flow

## 2.1 Manual invoice flow

```text
Client
  ↓
POST /invoices
  ↓
FastAPI
  ↓
Validate input
  ↓
Validate business rules
  ↓
Persist invoice
  ↓
Return invoice
```

Example request:

```json
{
  "invoice_number": "INV-2026-1001",
  "vendor": "ABC GmbH",
  "invoice_date": "2026-09-04",
  "currency": "EUR",
  "subtotal": 1000.00,
  "tax": 190.00,
  "total": 1190.00
}
```

Basic validation rules:

```text
invoice_number is required
vendor is required
invoice_date is valid
currency is supported
subtotal >= 0
tax >= 0
total >= 0
subtotal + tax == total
invoice_date is not in the future
vendor + invoice_number is unique
```

---

## 2.2 Excel import flow

```text
User uploads invoices.xlsx
        ↓
FastAPI accepts file
        ↓
Validate file type
        ↓
Validate required columns
        ↓
Parse rows
        ↓
Group rows into invoices
        ↓
Validate each invoice
        ↓
Persist valid invoices
        ↓
Generate import report
```

Recommended Excel columns:

```text
invoice_number
vendor
invoice_date
item
quantity
unit_price
tax_rate
currency
declared_subtotal
declared_tax
declared_total
```

One invoice may contain multiple rows because each row can represent one line item.

---

## 2.3 PDF / image invoice flow

```text
PDF / image uploaded
        ↓
Store file
        ↓
Create processing job
        ↓
Queue job
        ↓
Worker receives job
        ↓
OCR / document extraction
        ↓
Normalize extracted fields
        ↓
Run business validation
        ↓
Persist invoice
        ↓
Publish processing result
```

---

# 3. Final Domain Model

The project should gradually evolve toward the following domain concepts.

## Invoice

```text
id
organization_id
invoice_number
vendor_name
invoice_date
currency
subtotal
tax
total
status
source_type
created_at
updated_at
```

Possible `source_type` values:

```text
manual
excel
pdf
image
```

Possible invoice statuses:

```text
DRAFT
VALID
NEEDS_REVIEW
REJECTED
```

---

## InvoiceItem

```text
id
invoice_id
description
quantity
unit_price
tax_rate
line_subtotal
line_tax
line_total
```

---

## ImportJob

```text
id
filename
storage_key
status
total_rows
valid_rows
invalid_rows
created_at
started_at
completed_at
error_message
```

Possible statuses:

```text
UPLOADED
QUEUED
PROCESSING
COMPLETED
PARTIALLY_COMPLETED
FAILED
```

---

## ValidationIssue

```text
id
invoice_id
code
message
severity
field
expected_value
actual_value
```

Example issue codes:

```text
MISSING_REQUIRED_FIELD
INVALID_DATE
FUTURE_INVOICE_DATE
INVALID_CURRENCY
NEGATIVE_AMOUNT
TOTAL_MISMATCH
TAX_MISMATCH
DUPLICATE_INVOICE
LINE_TOTAL_MISMATCH
```

---

# 4. Engineering Rules for Claude Code

Claude must follow these rules during the entire project.

## 4.1 Phase isolation

When implementing a phase:

- Implement only the requirements of the current phase.
- Do not pre-build future architecture.
- Do not add Redis, Kafka, Celery, Kubernetes, microservices, CQRS, event sourcing, or other technologies unless explicitly requested by a later phase.
- Do not refactor unrelated code.
- Prefer the smallest correct change.

## 4.2 Explain before changing

Before coding, Claude should briefly explain:

1. What problem exists in the current code.
2. What this phase introduces.
3. Why this change is appropriate now.
4. Which files will be added or modified.

## 4.3 Keep the code beginner-readable

Until later phases:

- Prefer explicit code over clever abstractions.
- Avoid unnecessary generics.
- Avoid deep inheritance.
- Avoid metaprogramming.
- Avoid large utility frameworks.
- Avoid premature interfaces.
- Keep functions short and understandable.

## 4.4 Testing rule

Every phase that changes behavior must:

- Add or update tests.
- Run the test suite.
- Report failing tests.
- Do not move to the next phase until tests pass.

## 4.5 Git rule

Each completed phase should end with:

```bash
git status
git add .
git commit -m "<phase message>"
git tag <phase-tag>
```

Do not combine multiple phases into one commit.

---

# 5. Recommended Repository Evolution

The repository should **not** begin with the final structure.

It should evolve.

Initial:

```text
invoiceflow/
└── main.py
```

Later:

```text
invoiceflow/
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── messaging/
│   └── storage/
├── workers/
├── lambdas/
├── batch/
├── migrations/
├── tests/
├── infra/
├── deployments/
├── docs/
├── .github/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

# PHASE 0 — Repository Bootstrap

## Objective

Create the smallest possible FastAPI project and verify that the development environment works.

## Build

Create:

```text
invoiceflow/
├── main.py
├── requirements.txt
├── .gitignore
└── README.md
```

Install only what is needed:

```text
fastapi
uvicorn
```

Create:

```http
GET /
```

Response:

```json
{
  "message": "InvoiceFlow API"
}
```

Run locally with Uvicorn.

## Learn

- What FastAPI is.
- What Uvicorn is.
- What an ASGI application is at a basic level.
- Route.
- HTTP GET.
- JSON response.

## Do NOT add

- Database
- Pydantic models
- Routers
- Docker
- AWS
- Service layer
- Repository layer

## Definition of Done

- `uvicorn main:app --reload` works.
- `GET /` returns HTTP 200.
- `/docs` opens successfully.
- README contains local run instructions.

## Git tag

```text
v0.1-bootstrap
```

## Claude prompt

```text
Implement Phase 0 from the InvoiceFlow roadmap.
Keep the project intentionally minimal.
Do not introduce any architecture that belongs to future phases.
Explain the created files and how the request reaches the FastAPI route.
```

---

# PHASE 1 — In-Memory Invoice API

## Objective

Learn basic FastAPI route handling without persistence or architecture layers.

## Build

Use:

```python
invoices = []
```

Add:

```http
POST /invoices
GET /invoices
GET /invoices/{invoice_id}
```

For now, accept simple parameters or a basic dictionary.

Store invoices only in memory.

Example stored object:

```json
{
  "id": 1,
  "invoice_number": "INV-001",
  "vendor": "ABC GmbH",
  "subtotal": 1000,
  "tax": 190,
  "total": 1190
}
```

## Learn

- GET vs POST.
- Path parameters.
- Python lists and dictionaries as temporary storage.
- HTTP request/response flow.

## Expected limitation

Restarting the application deletes all invoices.

That limitation is intentional.

## Definition of Done

- Create invoice works.
- List invoices works.
- Fetch invoice by ID works.
- Restarting the server demonstrates why persistence will eventually be needed.

## Git tag

```text
v0.2-in-memory-api
```

---

# PHASE 2 — Pydantic Request Models

## Objective

Stop accepting loosely structured input.

## Build

Add a `BaseModel`:

```python
class InvoiceCreate(BaseModel):
    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
```

Use a JSON request body.

## Validation

At this phase, use only structural validation:

- required fields
- correct basic types
- valid date format

Do not yet implement complex business rules.

## Learn

- Request body.
- Pydantic.
- Type hints.
- Automatic validation.
- Swagger/OpenAPI schema generation.
- Why `Decimal` is preferable to float for money.

## Definition of Done

Invalid types return FastAPI validation errors automatically.

## Git tag

```text
v0.3-pydantic-request
```

---

# PHASE 3 — Response Models and HTTP Semantics

## Objective

Separate input representation from output representation.

## Build

Create:

```python
InvoiceCreate
InvoiceRead
```

`InvoiceRead` should include fields such as:

```text
id
status
created_at
```

Use:

```python
response_model=InvoiceRead
```

Use correct status codes:

```text
201 Created
404 Not Found
422 Validation Error
```

## Learn

- Request schema vs response schema.
- API contract.
- HTTP status codes.
- Why internal data should not automatically be exposed.

## Definition of Done

- POST returns 201.
- Missing invoice returns 404.
- API docs show separate request and response schemas.

## Git tag

```text
v0.4-api-contracts
```

---

# PHASE 4 — Basic Business Validation

## Objective

Introduce the difference between schema validation and business validation.

## Build

Create simple validation functions inside the current code.

Rules:

```text
subtotal >= 0
tax >= 0
total >= 0
subtotal + tax == total
invoice_date <= today
currency in {"EUR", "USD", "GBP"}
```

Do not create a service layer yet.

## Example

```text
subtotal = 1000
tax = 190
total = 1300
```

Should be rejected because:

```text
1000 + 190 != 1300
```

## Learn

- Structural validation vs business rules.
- Why syntactically valid data can still be invalid for the business.

## Definition of Done

Tests or manual examples prove each business rule works.

## Git tag

```text
v0.5-business-validation
```

---

# PHASE 5 — Routers and Package Structure

## Objective

Refactor only because `main.py` is becoming crowded.

## Build

Move toward:

```text
app/
├── main.py
├── routers/
│   └── invoices.py
└── schemas/
    └── invoice.py
```

Use:

```python
APIRouter
app.include_router(...)
```

## Learn

- APIRouter.
- Python modules.
- Separation by responsibility.

## Do NOT add

- Repository
- Service
- Database abstraction

## Definition of Done

Behavior remains unchanged after the refactor.

## Git tag

```text
v0.6-router-refactor
```

---

# PHASE 6 — PostgreSQL + SQLAlchemy

## Objective

Replace temporary in-memory storage with real persistence.

## Build

Add:

```text
PostgreSQL
SQLAlchemy
```

Create:

```text
app/db/
app/models/
```

Create an `Invoice` ORM model.

Initial table:

```text
invoices

id
invoice_number
vendor
invoice_date
currency
subtotal
tax
total
status
created_at
```

For this phase, direct database access inside the router is acceptable.

## Learn

- ORM.
- Table vs model.
- Engine.
- Session.
- Database connection.
- Commit.
- Refresh.
- Query.

## Definition of Done

- Restarting the application does not delete invoices.
- CRUD operations use PostgreSQL.
- Database connection is documented.

## Git tag

```text
v0.7-postgresql-sqlalchemy
```

---

# PHASE 7 — Alembic Migrations

## Objective

Version database schema changes.

## Build

Install/configure Alembic.

Create the initial migration.

Practice one real schema change, for example adding:

```text
updated_at
```

## Learn

- Migration.
- Revision.
- Upgrade.
- Downgrade.
- Why production databases must not depend on manual schema edits.

## Definition of Done

A new database can be created using:

```bash
alembic upgrade head
```

## Git tag

```text
v0.8-alembic
```

---

# PHASE 8 — Repository Layer

## Objective

Remove database-specific code from HTTP routes.

## Problem before this phase

Routers currently know about:

```text
Session
query
add
commit
refresh
```

## Build

Create:

```text
app/repositories/invoice_repository.py
```

Methods may include:

```text
create
get_by_id
list
find_by_vendor_and_invoice_number
```

## Rule

Repository handles persistence only.

It must not decide:

```text
whether invoice totals are valid
whether currency is supported
whether an invoice should be accepted
```

## Learn

```text
Router = HTTP
Repository = persistence
```

## Definition of Done

Routers no longer contain SQLAlchemy query logic.

## Git tag

```text
v0.9-repository-layer
```

---

# PHASE 9 — Service Layer

## Objective

Create a dedicated place for business logic.

## Build

Create:

```text
app/services/invoice_service.py
```

Move business rules from the router into the service.

Flow:

```text
Router
  ↓
InvoiceService
  ↓
InvoiceRepository
  ↓
PostgreSQL
```

Service responsibilities:

- validate totals
- validate invoice date
- validate currency
- check duplicate invoice
- create invoice

## Duplicate rule

A simple initial uniqueness rule:

```text
vendor + invoice_number
```

should not already exist.

## Learn

```text
Router = transport concerns
Service = business behavior
Repository = persistence
```

## Definition of Done

Business rules can be tested without making HTTP requests.

## Git tag

```text
v0.10-service-layer
```

---

# PHASE 10 — Dependency Injection

## Objective

Stop manually constructing repositories and services in routes.

## Build

Create FastAPI dependencies:

```text
get_db
get_invoice_repository
get_invoice_service
```

Route should become conceptually similar to:

```python
def create_invoice(
    data: InvoiceCreate,
    service: InvoiceService = Depends(get_invoice_service),
):
    return service.create(data)
```

## Learn

- FastAPI `Depends`.
- Dependency graph.
- Testability.
- Lifecycle of DB sessions.

## Definition of Done

Routes contain no manual `InvoiceRepository(...)` or `InvoiceService(...)` construction.

## Git tag

```text
v0.11-dependency-injection
```

---

# PHASE 11 — Configuration and Environment Variables

## Objective

Remove environment-specific values from source code.

## Build

Create:

```text
app/core/config.py
.env.example
```

Configure:

```text
DATABASE_URL
APP_ENV
LOG_LEVEL
```

Use a settings object.

## Security rule

Never commit real secrets.

## Learn

- Environment variables.
- Application configuration.
- Development vs production environments.

## Definition of Done

Application configuration changes without modifying source code.

## Git tag

```text
v0.12-config
```

---

# PHASE 12 — Application Exceptions and Error Handling

## Objective

Separate domain/business errors from HTTP errors.

## Build

Create exceptions such as:

```text
InvoiceNotFoundError
DuplicateInvoiceError
InvoiceValidationError
```

Create exception-to-HTTP translation.

Examples:

```text
InvoiceNotFoundError → 404
DuplicateInvoiceError → 409
InvoiceValidationError → 422
```

## Learn

Why the service layer should not be tightly coupled to FastAPI's `HTTPException`.

## Definition of Done

Service tests do not depend on FastAPI HTTP exceptions.

## Git tag

```text
v0.13-exceptions
```

---

# PHASE 13 — Logging

## Objective

Make important application activity observable.

## Build

Add structured, useful logs for:

```text
invoice_created
invoice_rejected
duplicate_detected
unexpected_error
```

Include useful context:

```text
invoice_id
invoice_number
vendor
```

Do not log:

```text
passwords
secrets
full confidential file contents
```

## Definition of Done

Important requests and failures can be understood from logs.

## Git tag

```text
v0.14-logging
```

---

# PHASE 14 — Automated Testing Foundation

## Objective

Protect existing behavior before the project becomes more complex.

## Build

Add:

```text
pytest
FastAPI TestClient or httpx test client
```

Test categories:

```text
unit tests
service tests
repository/integration tests
API tests
```

Minimum cases:

- create valid invoice
- invalid total
- future date
- unsupported currency
- duplicate invoice
- not found
- list invoices

## Definition of Done

Tests run with one command and pass consistently.

## Git tag

```text
v0.15-testing-foundation
```

---

# PHASE 15 — Invoice Items

## Objective

Move beyond header-only invoices.

## Build

Introduce:

```text
InvoiceItem
```

Fields:

```text
description
quantity
unit_price
tax_rate
line_subtotal
line_tax
line_total
```

Add relationship:

```text
Invoice 1 → N InvoiceItem
```

## Business rules

For each item:

```text
quantity > 0
unit_price >= 0
0 <= tax_rate <= 100
line_subtotal = quantity × unit_price
line_tax = line_subtotal × tax_rate
line_total = line_subtotal + line_tax
```

Invoice totals should be derived from items.

## Definition of Done

Invoice-level totals can be verified against line items.

## Git tag

```text
v0.16-invoice-items
```

---

# PHASE 16 — Standard Excel Template

## Objective

Introduce a realistic company import workflow.

## Build

Create a downloadable template endpoint:

```http
GET /templates/invoice-import
```

Template columns:

```text
invoice_number
vendor
invoice_date
item
quantity
unit_price
tax_rate
currency
declared_subtotal
declared_tax
declared_total
```

## Rule

The template is a documented public contract.

## Learn

- File responses.
- Import contracts.
- Versioning considerations.

## Definition of Done

User can download a valid `.xlsx` template.

## Git tag

```text
v0.17-excel-template
```

---

# PHASE 17 — Excel Upload and Structural Validation

## Objective

Accept `.xlsx` invoice files without processing business data yet.

## Build

Add:

```http
POST /imports
```

Validate:

- extension
- MIME/content type when practical
- workbook can be opened
- expected worksheet exists
- required columns exist
- file is not empty

Create an `ImportJob`.

## ImportJob response

```json
{
  "id": "imp_123",
  "filename": "invoices.xlsx",
  "status": "UPLOADED"
}
```

## Learn

- Multipart file upload.
- File validation.
- Excel parsing library.
- Separation of file structure validation from invoice validation.

## Definition of Done

Invalid Excel structure produces clear errors.

## Git tag

```text
v0.18-excel-upload
```

---

# PHASE 18 — Excel Row Parsing

## Objective

Convert spreadsheet rows into typed application data.

## Build

For every row:

- parse invoice number
- vendor
- date
- item
- quantity
- unit price
- tax rate
- currency
- declared totals

Normalize:

```text
whitespace
date formats
currency casing
decimal values
```

Do not persist invalid rows yet.

## Row-level errors

Track:

```text
row_number
field
error_code
message
```

## Definition of Done

The parser returns either:

```text
valid structured row
```

or:

```text
structured row error
```

for every spreadsheet row.

## Git tag

```text
v0.19-excel-row-parser
```

---

# PHASE 19 — Group Rows into Invoices

## Objective

Turn many Excel line-item rows into invoice aggregates.

## Build

Group by:

```text
vendor + invoice_number
```

Ensure invoice-level fields are consistent across rows.

Example problem:

```text
INV-1001 row 2 currency = EUR
INV-1001 row 3 currency = USD
```

This invoice must be flagged.

## Learn

- Aggregation.
- Cross-row validation.
- Domain consistency.

## Definition of Done

One multi-line invoice in Excel becomes one Invoice with many InvoiceItems.

## Git tag

```text
v0.20-excel-grouping
```

---

# PHASE 20 — Excel Business Validation and Import Report

## Objective

Run full invoice validation on imported Excel invoices.

## Build

Reuse the existing service/business rules.

Do not duplicate validation logic.

Generate import statistics:

```text
total_rows
parsed_rows
invalid_rows
invoices_found
valid_invoices
invalid_invoices
duplicate_invoices
```

Expose:

```http
GET /imports/{import_id}
```

Example result:

```json
{
  "status": "COMPLETED",
  "total_rows": 1000,
  "valid_rows": 943,
  "invalid_rows": 57,
  "invoices_created": 318
}
```

## Definition of Done

Excel imports reuse the same invoice business logic as manual invoice creation.

## Git tag

```text
v0.21-import-report
```

---

# PHASE 21 — Import Error Report

## Objective

Give users actionable feedback instead of a generic "import failed".

## Build

Expose errors such as:

```text
Row 12 → missing vendor
Row 18 → invalid date
Row 31 → quantity must be positive
Invoice INV-1008 → duplicate invoice
Invoice INV-1011 → total mismatch
```

Optional endpoint:

```http
GET /imports/{import_id}/errors
```

## Definition of Done

A business user can understand what needs to be corrected in the source spreadsheet.

## Git tag

```text
v0.22-import-errors
```

---

# PHASE 22 — Transaction Boundaries

## Objective

Prevent partially persisted invoice aggregates.

## Build

Define transaction rules.

Example:

```text
Invoice + all InvoiceItems
```

must either all succeed or all fail.

Decide explicitly how Excel imports behave:

Recommended:

```text
one transaction per invoice
```

This allows valid invoices to succeed even if other invoices fail.

## Learn

- Atomicity.
- Commit.
- Rollback.
- Transaction boundary.

## Definition of Done

A failed item insert cannot leave a half-created invoice.

## Git tag

```text
v0.23-transactions
```

---

# PHASE 23 — Dockerize the Application

## Objective

Package the application consistently.

## Build

Add:

```text
Dockerfile
.dockerignore
docker-compose.yml
```

Compose should support local:

```text
FastAPI
PostgreSQL
```

Do not add AWS yet.

## Learn

- Docker image.
- Container.
- Port mapping.
- Environment variables.
- Container networking.
- Persistent database volume.

## Definition of Done

A new developer can run the project with Docker without manually installing PostgreSQL.

## Git tag

```text
v0.24-docker
```

---

# PHASE 24 — Deployment Exercise: Lightsail

## Track

**Learning / alternative deployment**

## Objective

Experience the simplest AWS-hosted deployment model.

## Build

Deploy the application to Lightsail.

Document:

- machine setup
- application process
- environment variables
- exposed ports
- reverse proxy if used
- database strategy used for this exercise

## Important

Lightsail is not the planned final production architecture.

## Definition of Done

The API is publicly reachable and the deployment steps are documented.

## Git tag

```text
v0.25-lightsail
```

---

# PHASE 25 — Deployment Exercise: EC2

## Objective

Understand raw virtual-machine deployment.

## Build

Deploy on EC2 manually.

Learn/configure:

```text
AMI
instance type
SSH
Security Groups
public/private IP
Linux process management
Nginx or equivalent reverse proxy
environment variables
```

## Security

Do not expose PostgreSQL publicly.

## Definition of Done

You can explain every component between the browser and the FastAPI process.

## Git tag

```text
v0.26-ec2
```

---

# PHASE 26 — Deployment Exercise: Elastic Beanstalk

## Track

**Alternative managed platform**

## Objective

Compare managed application deployment with manual EC2 deployment.

## Build

Deploy the same application using Elastic Beanstalk.

Document:

```text
What Beanstalk manages
What you still manage
How it differs from EC2
When you would choose it
```

## Important

Do not keep Lightsail, EC2 manual deployment, and Beanstalk simultaneously in the final architecture.

## Git tag

```text
v0.27-beanstalk
```

---

# PHASE 27 — ECR

## Objective

Create an AWS-native container image workflow.

## Build

Create ECR repositories for:

```text
invoiceflow-api
```

Later workers may get separate repositories.

Workflow:

```text
Code
 ↓
docker build
 ↓
Docker image
 ↓
ECR
```

Use versioned image tags.

## Definition of Done

A locally built application image can be pushed to and pulled from ECR.

## Git tag

```text
v0.28-ecr
```

---

# PHASE 28 — ECS on EC2

## Objective

Understand container orchestration separately from serverless container compute.

## Build

Create:

```text
ECS cluster
task definition
service
desired count
EC2 capacity
```

Run the FastAPI image from ECR.

## Learn

- Cluster.
- Task definition.
- Task.
- Service.
- Desired count.
- Container health.

## Architecture

```text
ECR
 ↓
ECS
 ↓
EC2 capacity
 ↓
FastAPI containers
```

## Git tag

```text
v0.29-ecs-ec2
```

---

# PHASE 29 — ECS + Fargate

## Objective

Remove EC2 fleet management from the container runtime.

## Build

Move the ECS service to Fargate.

Architecture:

```text
ECR
 ↓
ECS
 ↓
Fargate
 ↓
FastAPI task
```

Define:

```text
CPU
memory
network configuration
environment
```

## Learn

```text
ECS = orchestration
Fargate = compute for containers
```

## Definition of Done

FastAPI runs on ECS without managing EC2 hosts.

## Git tag

```text
v0.30-fargate
```

---

# PHASE 30 — ALB + Health Checks + Scaling

## Objective

Create a scalable public API entry point.

## Build

Add:

```text
Application Load Balancer
Target Group
ECS service integration
```

Create:

```http
GET /health
```

Optionally:

```http
GET /ready
```

Configure health checks.

Run multiple API tasks.

## Architecture

```text
Internet
   ↓
  ALB
 ↙ ↓ ↘
API API API
```

## Learn

- Load balancing.
- Target groups.
- Health checks.
- Horizontal scaling.

## Definition of Done

Killing one API task does not make the public API unavailable.

## Git tag

```text
v0.31-alb
```

---

# PHASE 31 — S3 File Storage

## Objective

Stop treating application containers as permanent file storage.

## Build

Introduce a storage abstraction.

Start with:

```text
StorageService
```

Implementation:

```text
S3StorageService
```

Store:

```text
Excel imports
PDF invoices
image invoices
generated error reports
```

Database stores only metadata and storage keys.

Example:

```text
bucket: invoiceflow-dev
key: imports/2026/09/imp_123/invoices.xlsx
```

## Rule

Containers must remain disposable.

## Definition of Done

Restarting/replacing application containers does not lose uploaded files.

## Git tag

```text
v0.32-s3
```

---

# PHASE 32 — Asynchronous Import Processing with SQS

## Objective

Stop processing large Excel files inside the HTTP request.

## Current problem

Bad flow:

```text
Upload
 ↓
FastAPI
 ↓
Parse 20,000 rows
 ↓
Validate
 ↓
Wait
 ↓
Response
```

## New flow

```text
Upload
 ↓
FastAPI
 ├── store file in S3
 ├── create ImportJob
 └── send SQS message
        ↓
     return 202
```

Message example:

```json
{
  "import_id": "imp_123",
  "storage_key": "imports/imp_123/invoices.xlsx"
}
```

Create a separate worker:

```text
workers/import_worker/
```

Worker:

```text
receive SQS message
↓
mark PROCESSING
↓
download from S3
↓
parse
↓
validate
↓
persist
↓
mark COMPLETED
```

## Learn

- Queue.
- Producer.
- Consumer.
- Asynchronous processing.
- Decoupling.

## Definition of Done

`POST /imports` returns quickly even for large files.

## Git tag

```text
v0.33-sqs-worker
```

---

# PHASE 33 — Retry, Idempotency, and Dead-Letter Queue

## Objective

Make asynchronous processing safe.

## Problems to solve

SQS messages can be retried.

A worker can crash after saving data but before deleting a message.

The same import must not create duplicate invoices repeatedly.

## Build

Add:

- idempotent import processing
- retry policy
- Dead-Letter Queue
- processing attempt count
- failure reason
- safe state transitions

Suggested rule:

```text
ImportJob COMPLETED → processing same message again performs no duplicate work
```

## Learn

- At-least-once delivery.
- Idempotency.
- Retry.
- Poison message.
- DLQ.

## Definition of Done

Replaying the same message does not duplicate invoices.

## Git tag

```text
v0.34-reliability
```

---

# PHASE 34 — SNS Domain Events

## Objective

Avoid tightly coupling import processing to every downstream action.

## Publish events

Examples:

```text
invoice.created
invoice.needs_review
import.completed
import.failed
```

Flow:

```text
Worker
  ↓
 SNS Topic
 ↙   ↓   ↘
A    B    C
```

Possible subscribers:

```text
notification queue
audit queue
analytics queue
Lambda
```

## Rule

Core invoice processing must not need to know every subscriber.

## Learn

- Publish/subscribe.
- Fan-out.
- Domain events.
- Loose coupling.

## Git tag

```text
v0.35-sns-events
```

---

# PHASE 35 — Lambda for Event-Driven Utility Work

## Objective

Use serverless compute for short-lived event-driven work.

## Choose one narrow responsibility

Recommended examples:

```text
generate import summary metadata
write lightweight audit record
create small notification payload
generate a CSV error summary
```

Do not move the entire application to Lambda.

## Flow

```text
SNS event
  ↓
Lambda
  ↓
small isolated task
```

## Learn

- Event-driven function.
- Stateless execution.
- When Lambda is more appropriate than a long-running service.

## Git tag

```text
v0.36-lambda
```

---

# PHASE 36 — PDF and Image Invoice Intake

## Objective

Extend the product beyond standardized spreadsheets.

## Build

Add:

```http
POST /documents
GET /documents/{document_id}
```

Accepted initial file types:

```text
PDF
PNG
JPEG
```

Flow:

```text
Upload
 ↓
S3
 ↓
Document record
 ↓
Processing job
```

At this phase, do not perform OCR yet.

## Document model

```text
id
filename
content_type
storage_key
status
created_at
```

Statuses:

```text
UPLOADED
QUEUED
PROCESSING
EXTRACTED
NEEDS_REVIEW
FAILED
```

## Git tag

```text
v0.37-document-upload
```

---

# PHASE 37 — OCR / Document Text Extraction

## Objective

Extract machine-readable information from PDF/image invoices.

## Build

Introduce a document extraction adapter.

Concept:

```text
DocumentExtractor
```

Implementation can use:

```text
Amazon Textract
```

Keep provider-specific logic outside the invoice service.

Flow:

```text
S3 file
 ↓
Textract adapter
 ↓
raw extracted text / fields
```

Store raw extraction metadata separately from validated invoice data.

## Important

Do not trust OCR output automatically.

OCR output is input to the next validation/extraction stage.

## Definition of Done

The system can retrieve structured or textual extraction results for a sample document.

## Git tag

```text
v0.38-ocr
```

---

# PHASE 38 — Structured Invoice Field Extraction

## Objective

Convert unstructured extracted document data into the existing Invoice model.

## Target fields

```text
invoice_number
vendor
invoice_date
currency
subtotal
tax
total
line items when available
```

## Architecture

```text
Document
 ↓
OCR result
 ↓
Invoice field extractor
 ↓
InvoiceCandidate
 ↓
Existing invoice validation service
```

Create an intermediate object:

```text
InvoiceCandidate
```

Do not persist as a valid Invoice until business validation is complete.

## Extraction strategy

Start deterministic where practical.

Optional later improvement:

```text
AI-assisted structured extraction
```

but AI must not bypass validation.

## Definition of Done

PDF/image and Excel/manual invoices eventually converge on the same validation rules.

## Git tag

```text
v0.39-structured-extraction
```

---

# PHASE 39 — Review Workflow

## Objective

Handle invoices that cannot be automatically trusted.

## Build

Support:

```text
VALID
NEEDS_REVIEW
REJECTED
```

Expose endpoints such as:

```http
GET /invoices?status=NEEDS_REVIEW
POST /invoices/{id}/approve
POST /invoices/{id}/reject
```

Keep approval logic simple.

## Important

The system should not pretend uncertain OCR/extraction results are correct.

## Definition of Done

A questionable invoice can be reviewed and resolved without re-uploading the file.

## Git tag

```text
v0.40-review-workflow
```

---

# PHASE 40 — AWS Batch for Historical / Massive Imports

## Objective

Support workloads much larger than the normal real-time import pipeline.

## Use case

A new customer has:

```text
100,000 historical invoice files
```

that must be reprocessed.

This is different from a normal interactive request.

## Build

Add a bulk-import submission path.

Example:

```http
POST /bulk-imports
```

Architecture:

```text
FastAPI
 ↓
submit batch workload
 ↓
AWS Batch
 ↓
parallel processing jobs
```

Use AWS Batch for:

- large historical migrations
- massive reprocessing
- compute-heavy bulk transformations

Do not use Batch for ordinary single invoice requests.

## Git tag

```text
v0.41-aws-batch
```

---

# PHASE 41 — Terraform: Infrastructure as Code

## Objective

Stop manually creating the production AWS infrastructure.

## Build

Create:

```text
infra/terraform/
├── modules/
│   ├── network/
│   ├── ecr/
│   ├── ecs/
│   ├── alb/
│   ├── s3/
│   ├── sqs/
│   ├── sns/
│   ├── lambda/
│   └── batch/
└── environments/
    ├── dev/
    └── prod/
```

Manage with Terraform:

```text
VPC
subnets
security groups
ALB
ECS
Fargate
ECR
S3
SQS
DLQ
SNS
Lambda
AWS Batch resources
IAM roles/policies
```

## Rules

- No secrets in Terraform source.
- Prefer small understandable modules.
- Do not create modules just to create modules.
- Document inputs and outputs.
- Run formatting and validation.

Commands:

```bash
terraform fmt
terraform validate
terraform plan
terraform apply
```

## Git tag

```text
v0.42-terraform
```

---

# PHASE 42 — GitHub Actions CI

## Objective

Automatically validate code quality and tests.

## Pipeline

On pull request:

```text
Checkout
 ↓
Install dependencies
 ↓
Lint
 ↓
Run tests
 ↓
Optional type checks
```

Do not deploy from pull requests.

## Definition of Done

A broken test blocks the pull request pipeline.

## Git tag

```text
v0.43-ci
```

---

# PHASE 43 — GitHub Actions CD

## Objective

Automate application delivery.

## Pipeline

On merge to the deployment branch:

```text
Run tests
 ↓
Build Docker image
 ↓
Tag image
 ↓
Push to ECR
 ↓
Deploy new ECS task definition
 ↓
Wait for healthy service
```

Add a rollback strategy/documentation.

## Security

Use secure AWS authentication for CI/CD.

Do not store long-lived AWS credentials directly in the repository.

## Git tag

```text
v0.44-cd
```

---

# PHASE 44 — Observability and Operational Health

## Objective

Make the system diagnosable in production.

## Build

Improve:

```text
application logs
worker logs
health checks
processing duration metrics
failure counts
queue depth monitoring
DLQ visibility
```

Track useful application metrics:

```text
invoices_created_total
imports_completed_total
imports_failed_total
invoice_validation_failures_total
processing_duration
```

Document operational questions such as:

```text
How do I know workers are failing?
How do I know the queue is growing?
How do I know imports are getting slower?
How do I investigate a specific import?
```

## Git tag

```text
v0.45-observability
```

---

# PHASE 45 — Security Hardening

## Objective

Remove obvious production security weaknesses.

## Review

- IAM least privilege
- S3 access policies
- security groups
- secrets management
- file size limits
- allowed file types
- malicious upload considerations
- request validation
- dependency updates
- database network exposure
- logging of sensitive data
- CORS policy
- HTTPS

## Optional product expansion

Authentication and organizations may now be added if desired:

```text
Organization
User
Role
Permission
```

Do not add multi-tenancy earlier unless it becomes a specific project requirement.

## Git tag

```text
v0.46-security
```

---

# PHASE 46 — EKS Alternative Deployment

## Track

**Alternative architecture**

## Objective

Demonstrate Kubernetes knowledge without pretending that ECS and EKS are both necessary.

## Build

Create a separate deployment path:

```text
deployments/eks/
```

Learn/use:

```text
Pod
Deployment
Service
Ingress
ConfigMap
Secret
Horizontal Pod Autoscaler
```

Use the same application containers from ECR.

## Documentation requirement

README must explicitly state:

```text
ECS/Fargate is the primary production deployment.
EKS is an alternative Kubernetes implementation included for comparison and learning.
```

## Git tag

```text
v0.47-eks-alternative
```

---

# PHASE 47 — AWS Outposts Architecture Exercise

## Track

**Design-only**

## Objective

Demonstrate understanding of hybrid AWS architecture.

## Scenario

A regulated company requires invoice documents to remain processed in its local data center.

Design:

```text
AWS Region
   │
   ├── control / cloud services
   │
   └──────────────┐
                  │
          Customer Data Center
                  │
             AWS Outposts
                  │
          local processing
```

Create:

```text
docs/architecture/outposts-hybrid-design.md
```

Explain:

- why Outposts would be used
- what remains on-premises
- what remains in the AWS Region
- connectivity assumptions
- security boundaries
- operational trade-offs

Do not claim this environment was deployed.

## Git tag

```text
v0.48-outposts-design
```

---

# PHASE 48 — Final Architecture Review

## Objective

Clean up the project without rewriting it unnecessarily.

## Review

Check:

```text
Router responsibilities
Service responsibilities
Repository responsibilities
Configuration
Transactions
Error handling
Tests
Queue reliability
Storage boundaries
AWS IAM
Terraform structure
CI/CD
Documentation
```

Remove:

- dead code
- unused dependencies
- experimental scripts
- duplicate business validation
- undocumented environment variables

## Git tag

```text
v1.0-architecture-complete
```

---

# PHASE 49 — Portfolio-Grade README

## Objective

Make the repository understandable without reading the source first.

## README sections

### 1. Problem

Explain the business problem:

> Companies receive invoices in multiple formats and need to validate, import, and process them reliably.

### 2. Solution

Explain InvoiceFlow.

### 3. Features

Include:

```text
Manual invoice creation
Business validation
Excel bulk import
Import error reporting
S3 file storage
Asynchronous SQS processing
SNS domain events
Lambda event handling
PDF/image invoice processing
OCR extraction
Review workflow
AWS Batch bulk processing
ECS/Fargate deployment
Terraform
CI/CD
```

### 4. Architecture diagram

Show the primary architecture only.

### 5. Technology decisions

Explain:

```text
Why FastAPI?
Why PostgreSQL?
Why SQS?
Why SNS?
Why ECS/Fargate?
Why not EKS as the default?
Why AWS Batch?
```

### 6. Evolution

Document major stages:

```text
in-memory
database
layered backend
Excel import
Docker
AWS containers
async processing
document extraction
IaC
CI/CD
```

### 7. Local setup

Exact commands.

### 8. API examples

Example curl or HTTP requests.

### 9. Testing

How to run tests.

### 10. Deployment

Primary ECS/Fargate path.

### 11. Alternative architectures

- Elastic Beanstalk
- EKS
- Outposts design

## Git tag

```text
v1.1-portfolio-ready
```

---

# 6. Primary Production Architecture

The final **main** architecture should look approximately like this:

```text
                           Internet
                              │
                              ▼
                             ALB
                              │
                    ┌─────────┴─────────┐
                    │                   │
              FastAPI Task        FastAPI Task
                ECS/Fargate         ECS/Fargate
                    │                   │
                    └─────────┬─────────┘
                              │
                  ┌───────────┼───────────┐
                  │           │           │
             PostgreSQL      S3          SQS
                                          │
                                          ▼
                                   Import Worker
                                    ECS/Fargate
                                          │
                              ┌───────────┼───────────┐
                              │           │           │
                         PostgreSQL      S3          SNS
                                                   ↙  ↓  ↘
                                             Lambda SQS SQS
                                                    │   │
                                                Audit  Notifications

Large historical workloads
          │
          ▼
      AWS Batch

Container images
          │
          ▼
         ECR

Infrastructure
          │
          ▼
      Terraform

Delivery
          │
          ▼
   GitHub Actions
```

---

# 7. What Is Primary vs Alternative?

## Primary production path

Use this as the main portfolio architecture:

```text
FastAPI
PostgreSQL
Docker
ECR
ECS
Fargate
ALB
S3
SQS
SNS
Lambda
AWS Batch
Terraform
GitHub Actions
```

## Learning / alternative deployments

These should be documented as alternatives:

```text
Lightsail
EC2 manual deployment
Elastic Beanstalk
EKS
```

## Design-only

```text
AWS Outposts
```

Do not pretend every technology belongs in the same production request path.

---

# 8. Branch / Tag Strategy

Recommended simple strategy:

```text
main
```

For each phase:

```text
feature/phase-XX-short-name
```

Merge only after:

- implementation complete
- tests pass
- README/notes updated when necessary

Example tags:

```text
v0.1-bootstrap
v0.7-postgresql-sqlalchemy
v0.15-testing-foundation
v0.24-docker
v0.30-fargate
v0.33-sqs-worker
v0.38-ocr
v0.42-terraform
v1.0-architecture-complete
v1.1-portfolio-ready
```

---

# 9. Definition of Done for Every Phase

Before moving to the next phase, verify:

```text
[ ] Current phase requirements are fully implemented.
[ ] No future-phase architecture was introduced.
[ ] Application starts successfully.
[ ] Existing features still work.
[ ] Tests pass.
[ ] New behavior has tests where appropriate.
[ ] No real secrets are committed.
[ ] README/docs are updated if usage changed.
[ ] git diff has been reviewed.
[ ] One clean phase commit exists.
[ ] Phase tag has been created.
```

---

# 10. Standard Claude Code Prompt for Every Phase

Use this template when starting any phase:

```text
We are implementing Phase <NUMBER> of the InvoiceFlow roadmap.

Read the roadmap and inspect the current repository before making changes.

Rules:
1. Implement only this phase.
2. Do not introduce architecture or services from future phases.
3. Preserve existing behavior unless the current phase explicitly changes it.
4. Keep the code beginner-readable and avoid premature abstractions.
5. Before coding, explain:
   - the current problem,
   - what this phase changes,
   - which files you plan to modify or add.
6. Implement the smallest correct solution.
7. Add or update tests for changed behavior.
8. Run the relevant test suite.
9. At the end, provide:
   - summary of changes,
   - files changed,
   - commands to run,
   - tests executed,
   - any remaining limitations that are intentionally deferred to future phases.
10. Do not start the next phase.

Current phase:
<PASTE THE PHASE SECTION HERE>
```

---

# 11. Claude Code Review Prompt After Every Phase

After Claude implements the phase, run a second review:

```text
Review the implementation of the current InvoiceFlow phase as a senior backend engineer.

Check:
- correctness
- unnecessary complexity
- whether future-phase architecture was introduced too early
- FastAPI best practices appropriate for the current learning level
- validation behavior
- error handling
- transaction safety if relevant
- test quality
- naming
- security issues
- accidental breaking changes

Do not redesign the project.
Only identify concrete issues in the current phase and propose the smallest fixes.

Classify findings as:
- Critical
- Important
- Nice to improve

If there are no meaningful issues, say the phase is ready to close.
```

---

# 12. Learning Notes to Maintain

Create:

```text
docs/learning-log.md
```

After every phase write:

```markdown
## Phase X

### What I learned

### Why this phase was needed

### What problem existed before it

### New concepts

### Things I still do not fully understand

### One architecture decision I can now explain

### Interview questions I should be able to answer
```

This makes the repository useful for both learning and interview preparation.

---

# 13. Key Interview Questions the Finished Project Should Let You Answer

By the end, you should be able to explain:

1. Why did the project start without a repository layer?
2. What problem did the service layer solve?
3. What is the difference between a Pydantic schema and a SQLAlchemy model?
4. What does a SQLAlchemy session represent?
5. Why are transactions important during invoice imports?
6. Why use Decimal for monetary values?
7. Why process large Excel imports asynchronously?
8. What problem does SQS solve?
9. Why must an SQS consumer be idempotent?
10. What is a dead-letter queue?
11. What is the difference between SQS and SNS?
12. Why use S3 instead of container filesystem storage?
13. What is ECR?
14. What is the difference between ECS and Fargate?
15. Why put ALB in front of ECS tasks?
16. Why is EKS an alternative rather than an upgrade from ECS?
17. When would Lambda be preferable to a Fargate worker?
18. When is AWS Batch appropriate?
19. Why use Terraform?
20. Why should Terraform not contain secrets?
21. How does CI differ from CD?
22. What happens when one ECS task crashes?
23. Why should processing workers be stateless?
24. What is the difference between OCR extraction and business validation?
25. Why should uncertain OCR results go to `NEEDS_REVIEW`?
26. Why should the same validation service handle manual, Excel, and extracted invoices?
27. How do you prevent duplicate invoice imports?
28. How would you debug a growing SQS queue?
29. What is the production request path?
30. Which technologies in this repository are alternatives rather than simultaneous dependencies?

---

# 14. Final Success Criteria

The project is portfolio-ready when you can demonstrate all of the following.

## FastAPI

```text
Routing
Pydantic schemas
Dependency injection
Error handling
Configuration
File uploads
API documentation
Testing
```

## Backend engineering

```text
Layered responsibilities
Repository abstraction
Service layer
Business validation
Transactions
Idempotency
Background processing
Domain events
Operational logging
```

## Data

```text
PostgreSQL
SQLAlchemy
Alembic
Relationships
Import validation
Duplicate detection
```

## Containers

```text
Docker
ECR
ECS
Fargate
```

## AWS

```text
EC2
Lightsail
Elastic Beanstalk
ALB
S3
SQS
SNS
Lambda
AWS Batch
EKS
Outposts architecture
```

## Infrastructure

```text
Terraform
IAM
networking basics
environment separation
```

## Delivery

```text
Git
GitHub
CI
CD
tests before deployment
versioned container images
```

## Product behavior

```text
Manual invoice validation
Excel invoice import
Detailed import errors
Asynchronous processing
PDF/image upload
Document extraction
Invoice review workflow
Large historical batch processing
```

---

# 15. Most Important Rule

The value of this project is **not** that the final repository contains many AWS services.

The value is that every major architectural change has a reason:

```text
In-memory data
    ↓
we need persistence
    ↓
PostgreSQL

Routes contain DB code
    ↓
we need separation
    ↓
Repository

Business rules are scattered
    ↓
we need a domain layer
    ↓
Service

Large imports block HTTP
    ↓
we need asynchronous work
    ↓
SQS + Worker

One event needs multiple consumers
    ↓
we need pub/sub
    ↓
SNS

Containers need orchestration
    ↓
ECS

We do not want to manage hosts
    ↓
Fargate

Multiple tasks need one entry point
    ↓
ALB

Infrastructure is manually created
    ↓
Terraform
```

If you can explain **why each transition happened**, the project has achieved its main learning and portfolio goal.

---

# 16. Starting Point

Start only with:

```text
PHASE 0
```

When Phase 0 is complete and reviewed, move to Phase 1.

Do not ask Claude to generate the final architecture.

Build the architecture by earning each layer.
