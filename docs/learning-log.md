# Learning Log

One entry per completed phase of the
[implementation playbook](../InvoiceFlow_Claude_Code_Implementation_Playbook.md).

---

## Phase 0 — Repository Bootstrap

### What I learned

**FastAPI** is a Python web framework for building APIs. You declare routes as ordinary
Python functions and it handles the HTTP plumbing — parsing the request, calling the
function, serializing the return value to JSON, and generating API documentation from the
type hints.

**Uvicorn** is the server that actually listens on a TCP port. FastAPI by itself never
touches the network; it is only a collection of routes and the logic to dispatch to them.
Uvicorn accepts the connection, parses the HTTP request, and hands it to FastAPI.

**ASGI** (Asynchronous Server Gateway Interface) is the contract between those two halves.
It defines the shape of the object a server can call: roughly
`async def app(scope, receive, send)`, where `scope` describes the request, `receive` pulls
the request body, and `send` pushes the response back. Because both sides agree on that
contract, Uvicorn can be swapped for Hypercorn or Daphne without changing the application,
and FastAPI can be swapped for Starlette or Django without changing the server.

The whole request path in this phase:

```text
curl → TCP :8000 → Uvicorn → ASGI scope → FastAPI router → read_root() → dict
     → JSON encoding → HTTP 200 response → curl
```

A **route** is the pairing of an HTTP method and a path (`GET /`) with the function that
handles it. The `@app.get("/")` decorator registers `read_root` in FastAPI's routing table.

**HTTP GET** asks for a representation of a resource without changing server state. It is
safe (no side effects) and idempotent (calling it repeatedly changes nothing).

**JSON response** — returning a plain Python `dict` is enough. FastAPI serializes it and
sets `content-type: application/json` automatically.

### Why this phase was needed

Before writing any invoice logic, the development environment has to be proven to work.
If the server cannot start and return one hardcoded response, nothing built on top of it
can be trusted to fail for interesting reasons.

### What problem existed before it

An empty directory. No runnable code, no dependency list, no version control, and no
documented way for anyone else to start the project.

### New concepts

- ASGI application, and why the server/framework split exists
- Route registration via decorators
- Automatic OpenAPI schema generation and the `/docs` UI derived from it
- Pinned dependencies as a reproducibility tool
- `uv` as a venv + installer replacement when the system Python lacks `pip`

### Things I still do not fully understand

- When `async def` handlers matter versus plain `def`, and what FastAPI does differently
  for each (it runs sync handlers in a threadpool — but why, and when does that hurt?)
- What Starlette contributes versus what FastAPI adds on top of it
- How `--reload` detects changes, and why it is unsafe in production

### One architecture decision I can now explain

**Why the application does not include a database, routers, or a service layer yet.**
Each of those solves a problem that does not exist at this size. A repository layer exists
to keep SQL out of HTTP handlers — but there is no SQL. A service layer exists to give
scattered business rules a home — but there are no business rules. Adding them now would
mean writing indirection whose purpose could only be justified by pointing at a future
that hasn't arrived. The playbook's ordering is deliberate: let each layer be *earned* by a
concrete pain, so the reason for it is remembered rather than recited.

### Interview questions I should be able to answer

1. What is the difference between FastAPI and Uvicorn?
2. What is ASGI, and how does it differ from WSGI?
3. What happens, step by step, between `curl http://localhost:8000/` and the JSON response?
4. Where does the content of `/docs` come from?
5. Why pin dependency versions instead of installing whatever is latest?
6. Why is HTTP GET considered safe and idempotent?

---

## Phase 1 — In-Memory Invoice API

### What I learned

**GET vs POST.** `GET` asks for a representation and changes nothing — it is *safe* (no
side effects) and *idempotent* (running it ten times leaves the same state as running it
once). `POST` submits data and creates something new. It is neither: two identical `POST
/invoices` calls produce two invoices with different IDs. That asymmetry is why browsers
freely re-issue GETs but warn before re-submitting a form.

**Path parameters.** `@app.get("/invoices/{invoice_id}")` captures a URL segment and passes
it to the function argument of the same name. The annotation `invoice_id: int` is not
decoration — FastAPI converts the string from the URL and rejects what won't convert:

```text
GET /invoices/abc  →  422
{"detail":[{"type":"int_parsing","loc":["path","invoice_id"], ...}]}
```

**Lists and dicts as temporary storage.** `invoices = []` is a module-level list. It lives
in the Python process's heap, so it is created fresh when Uvicorn starts and disappears
when the process ends. `next_id` is a counter doing by hand what a database sequence will
later do automatically.

**The request/response flow, now with a body:**

```text
curl -X POST -d '{...}'
   → Uvicorn parses the HTTP request
   → FastAPI matches method + path to create_invoice
   → JSON body deserialized into the `invoice` dict parameter
   → function appends to the list, returns a dict
   → FastAPI serializes to JSON, sets content-type
   → HTTP 200 response
```

### Why this phase was needed

Phase 0 proved the server runs. It could not accept input or remember anything. Before
reaching for a database, it is worth building storage the crudest way possible, so the
reason for a database is something observed rather than assumed.

### What problem existed before it

One hardcoded route returning a fixed string. No concept of an invoice, no way to send data
in, no state at all.

### New concepts

- Request body vs path parameter vs query parameter
- Safe and idempotent HTTP methods
- Server-assigned identifiers, and an ID sequence as explicit mutable state
- `global` and module-level mutable state, and why it is uncomfortable
- Process memory as a storage medium, with its lifetime tied to the process

### Things I still do not fully understand

- With multiple Uvicorn workers, each process would hold a *separate* `invoices` list, so
  the same request could hit a worker that has never seen your invoice. Where exactly does
  that break down, and is it the same reason production APIs must be stateless?
- Is `global next_id` a race condition under concurrent requests? Python's GIL probably
  hides it here, but would it survive `async def` handlers or real threads?
- Why FastAPI accepts a bare `dict` annotation at all, and what it does with a body that
  isn't a JSON object

### One architecture decision I can now explain

**Why storing invoices in a Python list is the right amount of wrong for now.**

The list is indefensible as a product: data vanishes on restart, it cannot be shared across
processes, it cannot be queried, and nothing stops `{"nonsense": true}` from being stored
as an invoice. Every one of those is a real defect.

But writing it, then watching `GET /invoices` return `[]` seconds after creating two
invoices, converts "you need a database" from received wisdom into an observation. The same
applies to the accepted garbage payload, which is the argument for Phase 2's Pydantic
models, and to `GET /invoices/999` returning `null`, which is the argument for Phase 3's
HTTP semantics.

Building the flawed version first is what makes the fix explicable later. A repository
layer added today would be indirection over a list — motion without a reason. The playbook's
ordering is designed so each layer answers a pain that already exists.

### Interview questions I should be able to answer

1. What is the difference between a path parameter, a query parameter, and a request body?
2. Why is `POST` not idempotent, and where does that matter in a real system?
3. What happens to in-memory application state when the process restarts — and what happens
   when you run more than one instance behind a load balancer?
4. Why does `GET /invoices/abc` return 422 while `POST /invoices` accepts any JSON at all?
5. Why would you deliberately build a version you already know is wrong?

---

## Phase 2 — Pydantic Request Models

### What I learned

**Pydantic** turns a class of type-annotated attributes into a validator. `InvoiceCreate` is
not documentation — it is the executable rule for what a client may send.

**Automatic validation.** Annotating the parameter `invoice: InvoiceCreate` is the entire
integration. FastAPI reads the annotation, validates the body against it, and returns 422
with field-level detail *before the handler runs*. The handler never sees a malformed
invoice, so it needs no defensive checks:

```text
POST {"nonsense": true}
→ 422, seven errors, one per missing required field:
  invoice_number, vendor, invoice_date, currency, subtotal, tax, total
```

Errors carry a `loc` path pointing at the exact field — `["body","vendor"]` — which is what
makes a 422 actionable for a client instead of just a rejection.

**Type hints do real work here.** In most Python, annotations are inert; the interpreter
ignores them. Pydantic reads them at class-creation time and compiles a validator from them.
The same syntax that was a comment for a human becomes enforcement.

**OpenAPI schema generation.** The model is published at
`components.schemas.InvoiceCreate`, with `required` listing all seven fields, and `/docs`
renders it as a fillable form. One class definition produced the validator *and* the public
API documentation — they cannot drift apart, because they are the same source.

**Why `Decimal` rather than `float` for money.** Binary floating point cannot represent
`0.10` exactly, so errors accumulate: `0.1 + 0.2 == 0.30000000000000004`. On invoices that
is a cent that fails to reconcile, and it compounds across line items. `Decimal` stores
base-10 digits exactly, so `Decimal("0.1") + Decimal("0.2") == Decimal("0.3")` holds. This
becomes concrete in Phase 4, where `subtotal + tax == total` must be true as written rather
than true-to-within-epsilon.

**A wrinkle worth knowing.** JSON has no decimal type — only `number`. So amounts are
`Decimal` inside the application but serialize as floats on the way out: posting `1000.00`
returns `1000.0`. The right conclusion is not "Decimal was pointless" but that precision is
preserved where arithmetic happens and negotiated at the boundary. Systems that cannot
tolerate that boundary loss transmit money as an integer count of minor units, or as a
string.

**Lax coercion is the default.** `{"subtotal": "1000"}` is accepted and converted, while
`{"subtotal": "abc"}` is rejected. Pydantic converts when a conversion is unambiguous. Strict
mode exists but was not needed to satisfy this phase.

### Why this phase was needed

Phase 1 accepted `{"nonsense": true}` and stored it as an invoice. Every layer built above
that — business rules, a database schema, an import pipeline — would have inherited the
assumption that stored invoices have invoice-shaped fields, when nothing guaranteed it.
Validation belongs at the edge, where bad input can still be rejected cheaply.

### What problem existed before it

The request body was annotated `dict`, which told FastAPI only "parse JSON". Required fields,
types, and date formats were all unchecked. Payloads with no invoice data at all were stored
and returned with an assigned ID.

### New concepts

- Pydantic `BaseModel` as an executable input contract
- Validation at the boundary, before handler code runs
- Field-level error reporting (`type`, `loc`, `msg`, `input`)
- OpenAPI schema generated from the same class that enforces the rules
- `Decimal` vs binary float for monetary values, and the JSON boundary problem
- Lax vs strict type coercion
- Structural validation as distinct from business validation

### Things I still do not fully understand

- What happens to `Decimal` precision once PostgreSQL is involved in Phase 6 — is `NUMERIC`
  the column type that preserves it, and does SQLAlchemy return `Decimal` back?
- Whether `extra="forbid"` would be the better default for a real public API, given that
  ignoring unknown keys silently swallows client typos
- How Pydantic v2 can be this fast if it validates every request — where does the compiled
  validator actually live?
- Whether `date` should be `datetime` with a timezone for invoices crossing jurisdictions

### One architecture decision I can now explain

**Why structural validation and business validation are deliberately separate jobs.**

The model now guarantees an invoice *has the shape of* an invoice. It still permits this:

```json
{"subtotal": 1000, "tax": 190, "total": 9999,
 "currency": "XYZ", "invoice_date": "2099-12-31"}
```

Verified: that returns `200`. Every field is the right type, and the document is nonsense —
the arithmetic is wrong, the currency does not exist, and the invoice is dated 73 years in
the future.

The two kinds of validation answer different questions and have different lifetimes.
"Is `subtotal` a decimal?" is a property of the wire format; it is true in every deployment
and will never change. "Is `EUR` a currency we accept?" is a policy decision that varies by
customer and changes without the API contract changing. Encoding the second as
`Literal["EUR","USD","GBP"]` in the request schema would freeze a business rule into the
published OpenAPI document, and every currency the company adds would become a breaking
schema change.

Keeping them apart also puts the rules where every input path can reach them. Phase 20 must
run identical validation on Excel imports, and Phase 38 on invoices extracted from PDFs by
OCR. Neither arrives as an HTTP request body, so neither passes through this model — but
both must satisfy the same business rules. That is what Phase 9's service layer is for, and
it only works if the rules were never trapped in the HTTP schema.

### Interview questions I should be able to answer

1. What is the difference between a Pydantic schema and structural validation on one hand,
   and business rules on the other? Give an example that passes one and fails the other.
2. Why use `Decimal` instead of `float` for monetary amounts?
3. If amounts serialize to JSON floats anyway, what did `Decimal` actually buy you?
4. Where does the content of `/docs` come from, and why can it not drift from the validation?
5. What does a 422 response body contain, and why does `loc` matter to an API client?
6. Why not put the list of supported currencies in the request model?
7. What is the difference between lax and strict type coercion in Pydantic?

---

## Phase 3 — Response Models and HTTP Semantics

### What I learned

**Request schema vs response schema.** `InvoiceCreate` and `InvoiceRead` describe opposite
directions of travel. Create has seven fields, all client-supplied. Read has ten: the same
seven plus `id`, `status`, and `created_at`, which only the server may set. They were written
as two independent classes rather than one inheriting from the other, so neither can silently
reshape the other.

**`response_model` is enforcement, not documentation.** FastAPI validates the handler's
return value against the model and drops anything not declared. Because
`GET /invoices/{invoice_id}` now declares `response_model=InvoiceRead`, returning `None` is
no longer possible — which is exactly why the 404 became necessary rather than optional.

**HTTP status codes are part of the contract:**

| Code | Meaning here |
| --- | --- |
| `201 Created` | A new resource exists that did not before |
| `200 OK` | Here is the thing you asked for |
| `404 Not Found` | That resource does not exist |
| `422 Unprocessable Entity` | Well-formed JSON, but it fails the schema |

The `200` vs `201` distinction tells a client whether anything was created. The
`404` vs `422` distinction separates "your request was fine, the thing isn't here" from
"your request was malformed."

**`raise HTTPException` rather than returning an error.** Raising unwinds the handler, so
there is no path where a 404 is set and then more work happens anyway.

**An unexpected finding: adding `response_model` changed how money appears on the wire.**

```text
Phase 2 (no response_model):  "subtotal": 1000.0     JSON number
Phase 3 (response_model):     "subtotal": "1000.00"  JSON string
```

Two different serializers. Without a response model, the dict goes through FastAPI's
`jsonable_encoder`, which turns `Decimal` into `float`. With one, Pydantic serializes the
model itself, and it renders `Decimal` as a **string** — because string is the only JSON type
that can carry a decimal without going through binary floating point. The OpenAPI schema
confirms it: `InvoiceRead.subtotal` is now `type: string` with a decimal `pattern`.

**And that exposed a real precision trap on the way in:**

```text
sent  "subtotal": 1000.00   (JSON number)  ->  returned "1000.0"    scale lost
sent  "subtotal": "1000.00" (JSON string)  ->  returned "1000.00"   exact
sent  "tax": 0.10           (JSON number)  ->  returned "0.1"
sent  "tax": "0.10"         (JSON string)  ->  returned "0.10"
```

A JSON number is parsed into a binary float *before* Pydantic can convert it, and by then the
float has no memory of how many digits were written. A JSON string is handed to `Decimal`
verbatim. So choosing `Decimal` in the model was necessary but not sufficient — the boundary
format has to cooperate too. This is why financial APIs commonly transmit money as strings,
or as an integer count of minor units.

### Why this phase was needed

Phase 2 declared what clients may send but left what the API returns entirely implicit — the
response was whatever dict the handler happened to build. Two consequences were visible and
both were wrong: creating a resource returned `200` as though nothing had happened, and
asking for a nonexistent invoice returned `200 null`, which tells a client "success" and
"nothing" simultaneously.

### What problem existed before it

- `POST /invoices` returned `200` instead of `201`.
- `GET /invoices/999` returned `200` with a `null` body instead of `404`.
- The response shape was undocumented and unenforced; any change to the handler silently
  changed the API.
- Stored invoices had no `status` and no `created_at`.

### New concepts

- Separate input and output contracts for the same resource
- `response_model` as an output filter and validator
- Server-assigned fields that clients must not be able to set
- `201 Created`, `404 Not Found`, and how they differ from `422`
- `HTTPException` and raising rather than returning errors
- Two serializers (`jsonable_encoder` vs Pydantic) producing different wire formats
- Timezone-aware UTC timestamps as the default for stored times

### Things I still do not fully understand

- Should a `201` response carry a `Location` header pointing at `/invoices/{id}`? The spec
  suggests it; nothing here does it.
- With `response_model` filtering output, is there a performance cost to validating every
  response, and does `response_model_exclude_unset` matter for larger payloads?
- Is a JSON string the right public format for money, or should the API expose integer minor
  units (`119000` cents) and avoid the ambiguity altogether?
- When Phase 6 introduces the database, will `InvoiceRead` read from an ORM object instead of
  a dict, and what has to change for that to work?

### One architecture decision I can now explain

**Why one model cannot serve both directions.**

Reusing a single `Invoice` model for requests and responses looks like sensible deduplication
— today the two are nearly identical, and `InvoiceRead` repeats seven field declarations
verbatim. The duplication is real. It is also the cheaper mistake.

The two contracts are asymmetric in ways that only show up later. `id`, `status`, and
`created_at` are server-assigned: a shared model would let a client `POST` its own
`created_at`, or set `status: "VALID"` and skip the validation Phase 4 is about to add.
The asymmetry runs the other way too — Phase 45 adds users and organizations, where a
password is write-only, accepted on input and never returned. A single model has no way to
express "in but not out."

The failure mode is the direction that leaks. A field added for internal bookkeeping —
an audit note, an OCR confidence score in Phase 37, a customer's negotiated rate — becomes
public the moment it is added, because nothing declared that responses are a smaller set than
the stored record. `response_model` inverts that default: output is an allowlist, so
forgetting to expose something is a bug you notice, while accidentally exposing something is
not possible.

The honest caveat for today: `InvoiceRead` is currently a *superset* of what gets stored, so
the filter has nothing to filter. The mechanism is in place before it is needed, which is
unusual for this project — but it comes for free with the response model, rather than being
speculative architecture built on its own. It starts doing visible work in Phase 6, when a
database row carries columns that are not part of the API.

### Interview questions I should be able to answer

1. Why should an API declare separate request and response models for the same resource?
2. What does `response_model` actually do to a handler's return value?
3. When should an endpoint return `201` instead of `200`?
4. What is the difference between a `404` and a `422`?
5. Why can `GET /invoices/{id}` no longer return `None`?
6. Why did adding `response_model` change the JSON type of the money fields?
7. Why does sending `1000.00` as a JSON number lose precision when sending `"1000.00"` does
   not?
