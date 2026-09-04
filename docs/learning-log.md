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

---

## Phase 4 — Basic Business Validation

### What I learned

**Structural validation and business validation answer different questions.**

```text
InvoiceCreate asks:  is this shaped like an invoice?
validate_invoice asks: does this invoice make sense?
```

The gap between them is the whole phase. This payload passed the schema and was stored as a
real invoice at the end of Phase 3:

```json
{"subtotal":"1000","tax":"190","total":"9999",
 "currency":"XYZ","invoice_date":"2099-12-31"}
```

Every field is the correct type. The arithmetic is wrong, `XYZ` is not a currency, and the
invoice is dated 73 years from now. It now returns `422` with three issues.

**Why syntactically valid data can still be invalid for the business.** A type system can
check that `total` is a decimal. It cannot check that `total` is *the right* decimal, because
that depends on the other fields — and on rules a company chose, which no type expresses.
`subtotal + tax == total` is arithmetic; `currency in {EUR, USD, GBP}` is a policy someone
decided and could change tomorrow.

**Reporting every failure at once.** The rules run to completion and collect issues rather
than returning at the first problem. Verified:

```text
POST subtotal:-5 tax:-5 total:9999 currency:XYZ date:2099-12-31
→ 422 with 5 issues: NEGATIVE_AMOUNT×2, TOTAL_MISMATCH,
                     FUTURE_INVOICE_DATE, INVALID_CURRENCY
```

One round trip tells a client everything to fix. Stopping at the first failure would mean
five submissions to discover five problems, which becomes intolerable in Phase 20 when a
thousand-row spreadsheet is being validated.

**`Decimal` finally proved itself.** This invoice is accepted:

```text
subtotal 0.10  +  tax 0.20  ==  total 0.30      -> 201 VALID
```

The same comparison in binary float, verified in the same run:

```text
0.1 + 0.2 == 0.3   ->   False
0.1 + 0.2          ->   0.30000000000000004
```

Had the model used `float`, `TOTAL_MISMATCH` would fire on an invoice that is arithmetically
correct — and it would do so unpredictably, depending on which amounts happened to be
unrepresentable. Choosing `Decimal` in Phase 2 was a bet that paid off in Phase 4.

**Two 422 shapes now exist.** Schema failures carry `{type, loc, msg, input}`; business
failures carry `{code, field, message}`. Same status code, different bodies, because they
come from different layers.

### Why this phase was needed

Everything above the API — a database schema, an import pipeline, an accounting export —
would inherit the assumption that a stored invoice is a *real* invoice. Phase 3 guaranteed
only that it had invoice-shaped fields. The cheapest place to stop nonsense is the moment it
arrives, before anything downstream has acted on it.

It also unblocked `status`. It had been pinned to `DRAFT` since Phase 3 because nothing had
the authority to promote it. Now something does.

### What problem existed before it

Invoices whose totals contradicted themselves, whose currency did not exist, and whose dates
were in the future were accepted with `201` and stored. `status` was a field that never
changed.

### New concepts

- Business rules as code separate from the type system
- Accumulating errors rather than failing fast
- Machine-readable issue codes (`TOTAL_MISMATCH`, `NEGATIVE_AMOUNT`, …)
- Validation functions that return data instead of raising
- Rule boundaries: `<=` vs `<`, `>=` vs `>` — today's date is valid, zero is a valid amount
- Decimal arithmetic as a correctness requirement, not a style preference

### Things I still do not fully understand

- Is `422` right for a business-rule failure, or is `400` more accurate? Both are defensible;
  the playbook picks 422 in Phase 12, but I could not defend that choice from first
  principles yet.
- Should the two 422 shapes be unified? A client currently has to branch on which keys exist.
- `TOTAL_MISMATCH` fires alongside `NEGATIVE_AMOUNT` when an amount is negative, since a
  negative total also breaks the sum. Is that noise, or useful completeness?
- Where should `SUPPORTED_CURRENCIES` live once it becomes configurable per customer — Phase
  11's settings, or the database?

### One architecture decision I can now explain

**Why `validate_invoice` returns a list instead of raising an HTTP error.**

Raising `HTTPException` directly from inside the rules would be shorter — no return value to
inspect, no `if issues:` in the caller. It would also quietly weld the business rules to the
web framework, and the cost lands in three later phases at once.

Phase 20 has to run these exact rules over rows from a spreadsheet. There is no request to
fail there: a thousand-row import needs *every* invoice's issues collected into a report, and
one bad row must not abort the other 999. A function that raises can only reject one thing
and only in an HTTP context. A function that returns a list can be called in a loop.

Phase 38 has the same requirement for invoices extracted from PDFs by OCR, where a failure
should route the invoice to human review rather than return a status code to nobody.

And Phase 9 moves these rules into a service layer whose stated rule is that it must not
depend on FastAPI — precisely so it can be tested without HTTP and reused without a request.
By returning data now, that move is a cut-and-paste rather than a rewrite.

The general shape: **a function that computes an answer is reusable; a function that performs
a side effect is reusable only in the context that side effect belongs to.** The route
handler is the right place to decide that a list of issues means `422`, because the route is
the only part of this system that knows what HTTP is.

### Interview questions I should be able to answer

1. What is the difference between schema validation and business validation? Give an example
   that passes one and fails the other.
2. Why report every validation failure instead of returning at the first?
3. Why does `validate_invoice` return a list rather than raise an exception?
4. Show a concrete invoice where `float` would produce the wrong validation result and
   `Decimal` produces the right one.
5. Why is `currency in {EUR, USD, GBP}` a business rule rather than part of the schema?
6. Why is an invoice dated today accepted but one dated tomorrow rejected?
7. When would you store an invalid record instead of rejecting it outright?

---

## Phase 5 — Routers and Package Structure

### What I learned

**`APIRouter` is a FastAPI app's routing table without the app.** It collects routes in one
module, and `app.include_router(router)` mounts them onto the real application. The routes
themselves are written exactly as before — same decorators, same `response_model`, same
`status_code`.

```python
# app/routers/invoices.py
router = APIRouter(prefix="/invoices", tags=["invoices"])

# app/main.py
app.include_router(invoices.router)
```

**`prefix` and `tags` are what a router buys you.** The prefix is written once instead of on
every decorator; the tags group the routes under a heading in `/docs`.

**An empty path is not the same as `"/"`.** Under a `/invoices` prefix:

```text
@router.get("")   ->  /invoices     correct
@router.get("/")  ->  /invoices/    a different URL
```

Getting that wrong would have made the old URL a redirect. Verified afterwards:
`/invoices` returns 200 directly, and `/invoices/` returns 307 to it — the same as before.

**Python packages.** A directory with an `__init__.py` is a regular package, and
`from app.schemas.invoice import InvoiceCreate` walks that tree. Since Python 3.3 the
`__init__.py` is optional (the directory would become a namespace package), but writing it
is the convention and avoids surprises as the tree grows.

**The entrypoint moved:** `uvicorn main:app` became `uvicorn app.main:app`.

**How to verify a refactor.** A refactor claims a *difference is absent*, which is not
something a few spot-check requests can establish. What worked: capture the whole API surface
before touching anything, replay the identical battery afterwards, and diff.

```text
79 lines of recorded status + body     ->  diff empty
openapi.json                           ->  only the 3 "tags" additions
```

That diff caught something I would otherwise have shipped: rewording a docstring while moving
it changed the published OpenAPI `description`, because FastAPI exposes model docstrings in
the schema. Harmless, but it is a contract change, and this phase was supposed to change
nothing. Reverting the wording made the diff clean.

### Why this phase was needed

`main.py` had reached 159 lines holding five unrelated responsibilities: the FastAPI app, two
schemas, the in-memory store, the business rules, and four route handlers. Finding anything
meant scrolling past everything.

### What problem existed before it

One file that could only grow. Every future phase — a database, a repository, a service, an
Excel importer — would have added to the same module.

### New concepts

- `APIRouter`, `include_router`, router `prefix` and `tags`
- Regular packages, `__init__.py`, and dotted imports
- Empty-string route paths under a prefix, and why `"/"` differs
- Refactor verification by before/after diffing rather than spot checks
- Model docstrings being published in the OpenAPI schema

### Things I still do not fully understand

- The store (`invoices`, `next_id`) now lives in the router module. That is fine while it is
  temporary, but is module-level mutable state in a router ever acceptable long-term, or is
  Phase 6's database the only real answer?
- When routers grow, does `include_router` support nesting routers inside routers, and is
  that ever a good idea?
- Should `GET /` live in `main.py`, or belong to a `health` router once Phase 30 adds
  `/health` and `/ready`?

### One architecture decision I can now explain

**Why this structure arrived in Phase 5 and not Phase 0.**

The final tree in the playbook has ten directories — `api`, `core`, `db`, `models`,
`schemas`, `repositories`, `services`, `messaging`, `storage`, plus workers and lambdas.
Creating that on day one is the obvious move, and it is the wrong one.

Empty folders are claims about a design you have not tested. A `repositories/` directory
created before there is a database asserts that persistence will need an abstraction, that
this is where it goes, and that its boundary sits exactly there. Those may turn out true, but
in Phase 0 they are guesses, and guesses embedded in a directory tree are harder to abandon
than guesses in a function — nobody deletes a folder that "we'll need eventually," so the
project accretes structure it never earned.

The trigger to split was concrete and observable: the file got hard to read. That is a fact
about the code, not a prediction about it. Everything moved here already existed and was
already working, which is why the diff could be empty — the split was recognizing a boundary
that had formed on its own rather than imposing one in advance.

The same logic governs what did *not* move. `validate_invoice()` is still in the router,
sharing a file with HTTP concerns. That is a real smell, and Phase 9 exists to fix it. Fixing
it now would mean two phases doing one phase's work, and the reason for the service layer
would be "the folder was there" instead of "business rules and transport concerns were
tangled and it hurt."

### Interview questions I should be able to answer

1. What does `APIRouter` do, and how does it relate to the `FastAPI` app object?
2. Why is `@router.get("")` under a prefix different from `@router.get("/")`?
3. How would you prove a refactor changed no behavior?
4. Why not start a project with the directory structure it will eventually need?
5. What is `__init__.py` for, and what happens without it?
6. Why do the business rules still live in the router after this refactor?

---

## Phase 6 — PostgreSQL + SQLAlchemy

### What I learned

**ORM** — object-relational mapping. `Invoice` is a Python class; `invoices` is a PostgreSQL
table; SQLAlchemy translates between them. Assigning an attribute becomes an `UPDATE`,
`session.add()` becomes an `INSERT`, and a query returns objects instead of tuples.

**Table vs model.** There are now two files called `invoice.py`, and the difference is the
point:

```text
app/schemas/invoice.py    Pydantic   what crosses the API boundary
app/models/invoice.py     SQLAlchemy what is stored in PostgreSQL
```

They carry similar fields today and are not the same thing. A column can exist without being
exposed; a response field can be computed rather than stored.

**Engine.** Created once per process, owns the connection pool, and does not connect until a
statement actually runs. It is configuration, not a connection.

**Session.** A *unit of work*. It tracks the objects it has seen, batches the SQL, and holds
a transaction open until told otherwise. `SessionLocal` is a factory — `SessionLocal()` opens
one, and the `with` block closes it.

**Commit and refresh are two different ideas, and this phase made that concrete.**

```python
session.add(db_invoice)
session.commit()          # write the transaction; the row now exists
session.refresh(db_invoice)  # re-read it, so Python can see what the DB decided
```

`commit()` writes. It also *expires* the instance, marking every attribute as unknown. And
`id` was never in Python to begin with — the database assigned it from a sequence. Without
`refresh()` the object cannot report its own ID. Two operations because writing and reading
are two directions.

**Query.** `session.get(Invoice, 1)` fetches by primary key; `session.scalars(select(Invoice)
.order_by(Invoice.id)).all()` fetches many. The `order_by` is not decoration — the in-memory
list returned insertion order because it *was* a list, whereas a table has no inherent order.
Preserving the old behavior meant asking for it explicitly.

**`from_attributes=True`** is what lets `InvoiceRead` be built from an ORM object instead of a
dict — the answer to the question the Phase 3 log left open.

**`create_all()` only adds missing tables.** It cannot alter one that exists, so editing a
column and restarting does nothing at all. That is not a bug, it is the boundary of the tool,
and it is precisely why Phase 7 exists.

### Why this phase was needed

Phase 1 built storage the crudest possible way and left the defect in place for five phases:
restarting the process erased everything. The point was to make the reason for a database an
observation rather than an assumption. Verified, before and after:

```text
Phase 1:  POST, POST, restart, GET /invoices  ->  []
Phase 6:  POST × 6,      restart, GET /invoices  ->  6 invoices, ids [1..6]
                                  next POST     ->  id 7, not 1
```

### What problem existed before it

All application state lived in one process's memory. It could not survive a restart, could
not be shared between processes, could not be queried, and could not be inspected by any tool
other than the API itself.

### New concepts

- ORM, declarative models, `Mapped` / `mapped_column`
- Engine, connection pool, `Session` as a unit of work
- `commit()`, expiry-on-commit, `refresh()`
- Database-assigned identity columns and sequences
- `NUMERIC(precision, scale)` as the exact-decimal column type
- `from_attributes` for reading Pydantic models out of ORM objects
- `create_all()` and its inability to migrate

### Two things I got wrong, and what they cost

**1. I predicted `NUMERIC(12,2)` would reject a third decimal place. It rounds.**

PostgreSQL raises an error only when the *integer* part exceeds the precision; excess scale
is rounded silently. Verified:

```text
POST subtotal 0.005, tax 0.005, total 0.010   -> 201 Created
stored:      0.01        0.01        0.01
SELECT (subtotal + tax = total)               -> f
```

Business rules run on the Pydantic `Decimal`; the database applies its scale afterwards. So an
invoice can satisfy `TOTAL_MISMATCH` on the way in and violate it in storage. Recorded as a
known limitation rather than patched, because the fix is a new business rule and that is a
different phase's category.

The general lesson: **validation and storage constrain the same value in different places, and
nothing automatically keeps the two agreeing.**

**2. A database error escapes as a bare `500`.**

```text
POST subtotal 99999999999.00  ->  500 Internal Server Error
log: sqlalchemy.exc.DataError: (psycopg.errors.NumericValueOutOfRange)
```

Nothing catches `DataError`, so FastAPI's default handler returns an opaque 500 and the real
cause lives only in the server log. Phase 12 owns exception handling and is where this belongs.

### Things I still do not fully understand

- Each route opens its own session, so a request that read and then wrote would use two
  transactions. When does that start to matter, and is that what Phase 22's transaction
  boundaries are about?
- The session is closed by the `with` block, but the ORM object is returned afterwards and
  still serializes fine. Why does closing detach without expiring?
- `autoflush=False` was set without a clear reason beyond "fewer surprises." What would
  actually go wrong with it on?
- Is `String(3)` on `currency` doing real work, given the business rule already restricts it
  to three known values?

### One architecture decision I can now explain

**Why routes talk to the database directly here, when Phase 8 will say they must not.**

Every route now contains `with SessionLocal() as session:` and SQLAlchemy calls, so a single
function knows about HTTP status codes, business rules, and transactions at once. The playbook
explicitly permits this — *"For this phase, direct database access inside the router is
acceptable"* — and then spends Phase 8 taking it away.

That sequencing is the lesson. A repository is an indirection, and indirections are only worth
their cost against a problem you can point at. Writing `InvoiceRepository` before any SQL
exists means designing an interface for queries nobody has needed, and the usual result is an
abstraction shaped like the first thing that got written rather than like what the code
actually does.

By Phase 8 there will be three routes with session handling copy-pasted between them, a
duplicate check to add in Phase 9 that needs a fourth query, and tests in Phase 14 that want
to run without a live PostgreSQL. Those are concrete pressures, and the repository's shape
follows from them rather than from a guess.

What makes waiting safe is that the alternative is not "no structure" — it is *reversible*
structure. The queries are three lines in three functions. Moving them later is mechanical.
Building the wrong abstraction first is what is expensive, because everything downstream is
written against it.

### Interview questions I should be able to answer

1. What is the difference between a SQLAlchemy model and a Pydantic schema?
2. What does a `Session` represent, and how does it differ from a connection?
3. Why is `session.refresh()` needed after `session.commit()`?
4. Why is `NUMERIC` the right column type for money, and what is wrong with `FLOAT`?
5. What happens to a value with three decimal places in a `NUMERIC(12,2)` column?
6. Why does `create_all()` not solve schema changes?
7. Why does the list endpoint need an explicit `ORDER BY`?
8. Why is it acceptable — for now — for a route handler to run SQL directly?

---

## Phase 7 — Alembic Migrations

### What I learned

**Migration** — a file describing one change to the schema, with the code to apply it and the
code to undo it. The schema stops being whatever happened to run against the database and
becomes a reviewable, version-controlled sequence.

**Revision** — each migration's identifier, plus a pointer to the one before it. That forms a
chain, and `alembic_version` is a one-row table recording where a given database sits on it:

```text
<base> -> 1187a8364717  create invoices table
1187a8364717 -> e4fd0b79bf05  add updated_at to invoices  (head)
```

The same chain applied to any empty database produces the same schema. That is the whole
value.

**Upgrade and downgrade.** `alembic upgrade head` applies everything outstanding;
`downgrade -1` undoes the last one. Verified as a round trip: the `updated_at` column
disappeared and came back, and `downgrade base` → `upgrade head` rebuilt the schema from
nothing.

**`create_all()` had to go.** Leaving it would mean two mechanisms defining the schema, and
the one that cannot alter anything would usually win. Proved it is gone by starting the app
against an empty database: it serves requests happily and creates no tables.

### The lesson of the phase: autogenerate drafts, it does not decide

Adding `updated_at` to the model and running `--autogenerate` produced one line:

```python
op.add_column('invoices',
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
```

Applied to a table with one row in it:

```text
psycopg.errors.NotNullViolation: column "updated_at" of relation "invoices"
contains null values
```

Obvious in hindsight. Adding a `NOT NULL` column means every existing row instantly violates
the constraint, and there is no value to give them. Autogenerate compares *two schemas*. It
never looks at the rows, so it cannot know whether the table holds zero rows or ten million
— and against an empty table its one-liner is perfectly correct.

The fix is the standard three-step:

```python
op.add_column("invoices", sa.Column("updated_at", ..., nullable=True))  # 1 permit nulls
op.execute("UPDATE invoices SET updated_at = created_at")               # 2 backfill
op.alter_column("invoices", "updated_at", nullable=False)               # 3 enforce
```

Step 2 is a *decision*, not a mechanism: an invoice that has never been modified was last
changed when it was created. No tool could have chosen that.

The same trap applies to renames — autogenerate sees a dropped column and an added one, and
emits `DROP` + `ADD`, which silently destroys the data instead of moving it.

### Why this phase was needed

Phase 6 left the schema defined by `create_all()`, which only ever adds missing tables. A
column change to the model did nothing to an existing database, and it did nothing *silently*
— no error, no warning. There was also no record of what the schema was meant to be, so it
could not be reproduced on another machine, reviewed in a pull request, or reversed.

### What problem existed before it

The database's shape existed only as an accident of history. Reproducing it meant dropping
everything and starting over, which is not available in production.

### New concepts

- Migration, revision, revision chain, `head`, `base`
- `alembic_version` as the pointer into that chain
- `upgrade` / `downgrade` as inverse operations
- `--autogenerate` as schema diffing, and its blindness to data
- The add-nullable → backfill → enforce pattern
- Keeping the connection string in one place (`env.py` reads `DATABASE_URL`; `alembic.ini`'s
  placeholder is inert)

### Things I still do not fully understand

- Two people branching from the same revision would create two heads. How is that merge
  resolved?
- `op.alter_column(..., nullable=False)` takes a table lock. On a large table, how long, and
  what is the zero-downtime alternative?
- Should migrations run automatically at deploy, or as a separate step? Phase 43's CD
  pipeline will have to answer this.
- `downgrade` is easy for a column addition. Is it ever honest for a migration that dropped
  data, or is the real answer "restore from backup"?

### One architecture decision I can now explain

**Why production databases must never depend on manual schema edits.**

A hand-run `ALTER TABLE` works and is faster than writing a migration. What it does not do is
leave evidence. Nobody can tell later whether it ran, whether it ran on staging as well as
production, whether the person who ran it typed `varchar(50)` or `varchar(500)`, or how to
undo it. A new environment cannot be built, because the instructions were never written down
— they existed for a moment in somebody's terminal.

A migration turns each of those into a property of the repository. The change is a file, so
it is reviewed like code. `alembic_version` records what has been applied, so drift between
environments is a query rather than an argument. `downgrade` makes the reverse a plan instead
of an improvisation.

The deeper point is that the schema is part of the application, not part of the infrastructure
it happens to sit on. Code and schema change together — `updated_at` in the model is
meaningless without the column, and the column is dead weight without the model. Keeping them
in the same repository, advancing through the same review, is what keeps them consistent.

That is also why `create_all()` had to be deleted rather than kept as a convenience. Two paths
to a schema means two answers to "what does this database look like," and the one that cannot
migrate is the one that silently does nothing.

### Interview questions I should be able to answer

1. What is a database migration, and why not just run `ALTER TABLE` by hand?
2. What does `alembic upgrade head` actually do?
3. Why can `--autogenerate` produce a migration that fails in production but passes locally?
4. How do you add a `NOT NULL` column to a table that already has rows?
5. Why is `create_all()` not a substitute for migrations?
6. What happens when two developers each add a migration on the same parent revision?
7. Where should the database connection string live, and why not in `alembic.ini`?
