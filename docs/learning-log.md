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

---

## Phase 8 — Repository Layer

### What I learned

**Router = HTTP. Repository = persistence.** Two sentences, and the whole phase follows from
them. A route's job is to translate between HTTP and the application: read a body, pick a
status code, raise a 404. A repository's job is to put objects in a database and get them
back. Neither should be able to describe the other's work.

Before, one function did both:

```python
with SessionLocal() as session:
    session.add(db_invoice)
    session.commit()
    session.refresh(db_invoice)
    return db_invoice
```

After:

```python
with SessionLocal() as session:
    return InvoiceRepository(session).create(db_invoice)
```

**The session is injected, not created.** `InvoiceRepository(session)` takes the session
through `__init__`. A repository that opened its own session could never share a transaction
with anything else — and Phase 22 needs an invoice and all its items to commit or fail
together.

**`create()` takes an `Invoice`, not an `InvoiceCreate`.** The repository must not depend on
the API's request schema. Phase 20's Excel importer will save invoices that never came from
an HTTP body, and it will call this same method.

**A method named `list` is a trap.** Defining `def list(self)` inside a class body shadows the
builtin for every *later* annotation in that body, so a subsequent `-> list[Invoice]` raises
`TypeError`. Named it `list_all`.

**Verifying a refactor, again.** Same method as Phase 5: capture the API surface before,
replay after, diff.

```text
79 request/response pairs   ->  diff empty
openapi.json                ->  byte-identical
```

One new wrinkle: IDs now come from a database sequence, so both runs had to start from a
truncated table to be comparable. In Phase 5 the in-memory list reset itself on restart; a
database does not forget.

**Checking the Definition of Done mechanically.** "Routers no longer contain SQLAlchemy query
logic" is greppable, so it was checked by grep rather than by reading:

```bash
grep -nE 'session\.(add|commit|refresh|get|query|scalars|execute)|select\(' \
     app/routers/invoices.py     # no matches
```

### Why this phase was needed

Three routes had session handling copy-pasted between them, and each one had three unrelated
reasons to change: an HTTP contract change, a business-rule change, or a persistence change.
The Phase 6 log predicted this pressure would build by Phase 8, and it did — exactly three
copies.

### What problem existed before it

Routes knew about `Session`, `add`, `commit`, `refresh`, `select` and `get`. Changing how
invoices were stored meant editing every route that stored one.

### New concepts

- Repository as a persistence boundary
- Constructor-injected sessions, and why the repository must not own one
- Repositories accepting domain objects rather than request schemas
- Greppable definitions of done
- Baseline resets when identity is database-assigned

### Things I still do not fully understand

- `create()` commits. That works for one entity — what does it become in Phase 22 when an
  invoice and its items must be atomic? Presumably the commit moves out, but to where?
- Should `get_by_id` returning `None` be the repository's answer, or should it raise? Right
  now the router turns `None` into a 404, which feels right, but Phase 12 adds
  `InvoiceNotFoundError` and I am not sure which layer will raise it.
- Is `list_all()` viable once there are 100,000 invoices? Nothing paginates.

### One architecture decision I can now explain

**Why the repository is forbidden from knowing what a valid invoice is.**

The playbook states the rule flatly: the repository must not decide whether totals are valid,
whether a currency is supported, or whether an invoice should be accepted. Enforcing it
produces a class that will cheerfully store garbage — demonstrated rather than assumed:

```text
repository.create(invoice with currency XYZ, dated 2099,
                  subtotal -5, tax -5, total 9999)
  -> stored, id=7

POST the same invoice to the API
  -> 422 with 5 issues
```

Two different answers to the same data, and both are correct. The API is a policy boundary;
the repository is a storage boundary.

The temptation is to add the check "just in case" — defence in depth, a guard against a future
caller who forgets. What that actually buys is a second copy of the rules, which will drift
from the first, and a repository that cannot be reused. Phase 20's Excel importer must be able
to store an invoice it has *already* validated, and Phase 39's review workflow must be able to
store one it has explicitly decided is `NEEDS_REVIEW` — an invoice known to be wrong, kept
deliberately so a human can fix it. A repository that refuses invalid data cannot serve either.

The deeper principle: **validation is a decision, storage is a mechanism.** Decisions vary by
context and change with the business; mechanisms do not. Putting a decision inside a mechanism
means every future caller inherits a judgement that was made for someone else's use case.

### Interview questions I should be able to answer

1. What belongs in a router, and what belongs in a repository?
2. Why does the repository receive a session instead of creating one?
3. Why shouldn't a repository validate the data it stores?
4. Why does `create()` take an ORM object rather than the request schema?
5. How would you prove a refactor changed no behavior when IDs come from a database sequence?
6. What breaks if a repository commits, and you later need two writes to be atomic?

---

## Phase 9 — Service Layer

### What I learned

**Three layers, three jobs:**

```text
Router       transport      what a 422 is, what a request body looks like
Service      behavior       what a valid invoice is, what a duplicate means
Repository   persistence    how rows get in and out of a table
```

The router shrank from 117 lines to 43, and every line left in it is about HTTP.

**The duplicate rule is why the rules had to move.** The other six rules can be answered by
looking at the invoice alone. This one cannot:

```python
if self.repository.find_by_vendor_and_invoice_number(data.vendor, data.invoice_number):
```

It needs to know what is already stored. A rule that needs the database cannot live in the
router, because the router is not supposed to have one. That is the concrete pressure that
made this phase necessary rather than decorative.

**The service imports no FastAPI.** Verified rather than assumed — importing
`app.services.invoice_service` loads zero `fastapi` modules, and its only top-level imports
are `datetime` and `app`. That is what makes the Definition of Done achievable: **10 rule
checks ran with no uvicorn, no client, no HTTP.**

**The cost of that independence is a tuple.** `create()` returns `(invoice, issues)`:

```python
created, issues = service.create(invoice)
if issues:
    raise HTTPException(status_code=422, detail=issues)
return created
```

It cannot raise `HTTPException` without depending on the web framework, and domain exceptions
are Phase 12. So the awkwardness is deliberate and temporary — it is exactly the discomfort
Phase 12 exists to relieve.

**Verifying a phase that is not a pure refactor.** Phases 5 and 8 demanded an empty diff.
This one changes behavior, so the standard becomes: *predict the diff, then confirm it is
exactly that*. Predicted two changed entries — the deliberate duplicate going `201 -> 422`,
and the list dropping from 6 invoices to 5. Both appeared, nothing else did.

The subtle thing that had to be checked: the rule-failure cases run *before* any invoice is
stored, so they must not pick up a spurious `DUPLICATE_INVOICE`. They didn't.

### A race I found, and the honest version of the story

`create()` checks for a duplicate and then inserts, with no constraint underneath. I fired 12
concurrent identical requests expecting duplicates to slip through:

```text
12 concurrent POSTs -> 1 x 201, 11 x 422       one row stored
```

It did not reproduce. That is not the same as being safe, so I forced the interleaving
directly:

```text
session A: find_by_vendor_and_invoice_number -> None
session B: find_by_vendor_and_invoice_number -> None
session A: INSERT -> id 1
session B: INSERT -> id 2      two rows, same vendor + invoice_number
```

Two rows. The race is real; the window is just narrow enough that ordinary load does not hit
it. **A test that passes under concurrency is not proof of correctness — it can be proof of
timing.**

The real fix is a unique constraint, making the database the arbiter instead of a prior
`SELECT`. That needs a migration plus `IntegrityError` handling, which wants Phase 12's
machinery. Recorded in the README rather than patched here.

### Why this phase was needed

70 of the router's 117 lines were business rules. Changing what makes an invoice valid meant
editing the HTTP layer, and the duplicate rule could not be written at all, because it needed
a database the router had no business touching.

### What problem existed before it

Business rules lived inside a FastAPI route function. They could not be called without an
HTTP request, could not query anything, and could not be reused by the Excel importer or
document extractor that later phases require.

### New concepts

- Service layer as the home for business behavior
- Returning results instead of raising, to avoid framework coupling
- Rules that require state, and why they force a layer boundary
- Predicting a behavior diff instead of demanding an empty one
- Check-then-insert races, and why load testing does not prove their absence

### Things I still do not fully understand

- `create()` calls `validate()`, which queries the database, then inserts. Should the whole
  operation be one transaction with the row locked, or is the unique constraint the only real
  answer?
- Reads bypass the service entirely. When Phase 39 adds `?status=NEEDS_REVIEW`, does filtering
  become business behavior, or is it still just a query?
- `validate()` is public so it can be tested. Is exposing it a design decision or a testing
  convenience leaking into the API?

### One architecture decision I can now explain

**Why the service must not know FastAPI exists.**

Raising `HTTPException(422, ...)` from inside `InvoiceService` would be shorter and read more
naturally than returning a tuple the caller has to unpack. The reason not to is that it would
make "this invoice is invalid" and "the HTTP response should be 422" the same statement, when
they are two different claims made by two different layers.

The costs land in phases that are already on the roadmap. Phase 20's Excel importer validates
a thousand rows and produces a report — there is no response to set a status code on, and one
bad row must not abort the other 999. Phase 38 extracts invoices from PDFs, where a failure
routes the invoice to human review rather than to a client. Phase 14 wants to assert that a
future-dated invoice is rejected without starting a web server. A service that raises
`HTTPException` serves none of them, and the usual workaround — catching the framework's
exception outside the framework — is worse than the tuple.

There is a testing argument too, and the Definition of Done makes it the point of the phase:
*business rules can be tested without making HTTP requests*. Ten rules were checked by calling
a Python method. No server, no port, no client, no serialization. When those tests fail they
fail on the rule, not on transport.

The general shape: **a layer should depend on what it needs, not on what called it.** The
service needs a repository and a clock. It does not need to know that something upstream
speaks HTTP — and the moment it does, everything that is not HTTP is locked out.

### Interview questions I should be able to answer

1. What belongs in a router, a service, and a repository?
2. Why shouldn't a service raise `HTTPException`?
3. What is the cost of that rule, and how does it get paid back later?
4. Which business rule forced the service layer to exist, and why couldn't it live in the router?
5. Why is a duplicate check that passes 12 concurrent requests still not safe?
6. How do you verify a phase that deliberately changes behavior?
7. Why is `409` a better status for a duplicate than `422`?

---

## Phase 10 — Dependency Injection

### What I learned

**`Depends` inverts who does the building.** Before, each route constructed its own
collaborators:

```python
with SessionLocal() as session:
    service = InvoiceService(InvoiceRepository(session))
```

Now the route states a requirement and FastAPI satisfies it:

```python
def list_invoices(repository: InvoiceRepositoryDep):
    return repository.list_all()
```

`app/routers/invoices.py` ended up importing neither `InvoiceService`, `InvoiceRepository` nor
`SessionLocal`. Confirmed by parsing the module rather than reading it: the only functions it
calls are `APIRouter` and `HTTPException`.

**The dependency graph.** Each provider asks for the one above it instead of building it:

```text
get_db()  ->  get_invoice_repository(session)  ->  get_invoice_service(repository)
```

FastAPI resolves the chain per request, so every layer shares one session. The useful
consequence is that overriding a dependency redirects everything beneath it — replacing
`get_db` swaps the database for the repository and the service at once, without either
knowing.

**Session lifecycle, and why `yield` rather than `return`.** FastAPI runs the generator up to
the `yield`, hands over the session, and resumes it once the response has been sent. Inspected
directly:

```text
after next(gen):  session active = True
after resuming:   generator finished -> the with block closed the session
gen.throw(...):   exception propagates, and the session is still cleaned up
```

One session per request, closed exactly once, on both the success and failure paths.

This is a real change from Phase 9, where each route closed its session *before* returning and
serialization happened against a detached object. The session now stays open while the
response is serialized. The behavior battery came back byte-identical, so nothing depended on
the old ordering — but it could have, which is why it was worth diffing rather than assuming.

**Testability — the payoff, and why `Annotated` matters for it.** With
`Annotated[X, Depends(f)]` the parameter has no default, so the route is a plain function:

```text
create_invoice(invoice=data, service=StubService())  -> HTTPException 422 ['STUB']
get_invoice(invoice_id=999, repository=StubRepo())   -> HTTPException 404
list_invoices(repository=StubRepo())                 -> ['a', 'b']
```

No app, no server, no database. And through FastAPI, the same substitution:

```text
app.dependency_overrides[get_invoice_service] = lambda: StubService()
POST /invoices -> 422, detail codes ['OVERRIDDEN']
```

The real service and the database were never reached. That is the mechanism Phase 14's test
suite will be built on.

### Why this phase was needed

The construction `InvoiceService(InvoiceRepository(session))` appeared in every route that
needed it, and the session lifecycle was restated three times. Both are the kind of detail
that is eventually wrong in exactly one place.

### What problem existed before it

Routes were welded to concrete classes. Nothing could be substituted, so testing a route meant
having a real database, and changing how a service is built meant editing every route.

### New concepts

- `Depends`, and dependencies that depend on dependencies
- `Annotated[X, Depends(f)]` versus the default-value form
- Generator dependencies and per-request resource lifecycles
- `dependency_overrides` as the seam for tests
- Verifying a claim about a module by parsing it rather than grepping it

### Things I still do not fully understand

- Dependencies are resolved per request. Is `InvoiceService` constructed on every single
  request, and does that ever matter?
- `get_db` yields inside a `with`. What happens if the response itself fails to serialize —
  after the yield but before the generator resumes?
- Overriding `get_db` should redirect everything below it. Does that hold when a dependency
  is cached within a request, and what is `use_cache` for?

### A note on tooling, not code

PostgreSQL stopped partway through this phase — a WSL restart, most likely — and every request
started returning `500`. The traceback said `connection refused`, not anything about the
application. Worth recording because the symptom (`500` on a route that worked minutes
earlier) looks exactly like a regression, and the log was the only thing that distinguished
the two. It is also a preview of Phase 12: an unhandled infrastructure failure surfacing as an
opaque 500 with the real cause visible only server-side.

### One architecture decision I can now explain

**Why injection is worth it now, and would have been ceremony in Phase 2.**

The same three files could have been written on day one. FastAPI supports it, tutorials show
it, and it would have looked more professional. It would also have been pure overhead, because
in Phase 2 there was nothing to inject — no database, no repository, no service. A `get_db`
dependency in a project whose storage is a Python list is a mechanism with no purpose,
justified only by the belief that it will have one later.

What makes it worth its cost now is that there is finally something worth substituting.
Between Phase 6 and Phase 9 the project acquired a session with a lifecycle, a repository that
talks to real PostgreSQL, and a service holding rules worth testing in isolation. Injection is
valuable in proportion to how much you want to vary what gets injected, and that quantity was
zero until very recently.

The general shape: **indirection buys optionality, and optionality is only worth its cost when
you can name the option.** Here the options are concrete — a test database instead of the real
one, a stub service instead of the real one, and in Phase 14 both at once.

It also explains the ordering. Injection had to come after the service and repository existed,
because injecting them requires them to exist. Doing it earlier would have meant designing an
interface for classes not yet written — which is the same mistake as writing
`find_by_vendor_and_invoice_number` before anything called it.

### Interview questions I should be able to answer

1. What does `Depends` actually do, and when does FastAPI resolve it?
2. Why does `get_db` use `yield` instead of `return`?
3. What is the difference between `Annotated[X, Depends(f)]` and `x: X = Depends(f)`?
4. How would you point your tests at a different database without editing any route?
5. Why is dependency injection not worth adding to a project on day one?
6. When is the database session closed relative to response serialization, and why might that
   matter?

---

## Phase 11 — Configuration and Environment Variables

### What I learned

**Environment variables are how a process is told where it is running.** The same code has to
work against a laptop's PostgreSQL, a staging database and a production one. The only thing
that differs is a handful of values, and those values are supplied from outside the program.

**A settings object gives configuration one home.** Before, the only configurable value was an
`os.getenv` call buried in the module that builds the SQLAlchemy engine. Answering "what can
this application be configured with" meant grepping. Now `app/core/config.py` is the single
answer, and verified as such — there is no `os.getenv` or `os.environ` anywhere else in `app/`
or `migrations/`.

**Resolution order, confirmed by running it:**

```text
environment variable   >   .env   >   default in config.py
```

```text
.env sets APP_ENV=production        -> app_env=production
APP_ENV=staging on top of that      -> app_env=staging
.env removed                        -> app_env=development
```

**Types make configuration fail early.** `Literal[...]` and `PostgresDsn` are not decoration:

```text
LOG_LEVEL=VERBOSE     -> log_level: Input should be 'DEBUG', 'INFO', 'WARNING', ...
APP_ENV=prod          -> app_env: Input should be 'development', 'staging' or 'production'
DATABASE_URL=not-a-url -> database_url: Input should be a valid URL
```

Each names the field and stops the process at import. Without that, `LOG_LEVEL=VERBOSE` would
be accepted silently and simply never match anything — the kind of bug that is invisible until
someone wonders why production has no debug logs.

I checked `PostgresDsn` before relying on it, since a parsed-URL type can normalise what it
round-trips. It returns the input byte-for-byte here, and rejects a wrong scheme
(`mysql://...`). It does accept a URL with no database name, which is worth knowing.

**Proving a setting actually reaches the thing it configures.** Printing `settings.database_url`
only proves the settings object parsed it. The real test is whether the *engine* uses it:

```text
DATABASE_URL=...localhost:5432/does_not_exist
-> FATAL: database "does_not_exist" does not exist
```

The failure names the configured database, so the value travelled the whole way. A config
value that is read but never used looks identical to one that works.

**A dependency that quietly disappeared.** `migrations/env.py` used to import `DATABASE_URL`
*from the session module* — Alembic depended on the engine module purely to read a string. Both
now read `app.core.config`, and neither imports the other.

### Why this phase was needed

Configuration was a single `getenv` with a hardcoded fallback, undiscoverable and unvalidated,
sitting in a file whose job was something else entirely. Everything from Phase 23's containers
onward assumes the same artifact runs in several environments, which only works if the
differences between them live outside the code.

### What problem existed before it

No single place listing what could be configured. No validation. No `.env` support. And
Alembic reaching into the session module for a string.

### New concepts

- Settings object as the single reader of the environment
- `pydantic-settings`, `.env` files, and resolution precedence
- Validating configuration at import time rather than at first use
- `PostgresDsn` and `Literal` as configuration types
- `.env.example` as the committed documentation of every knob

### Things I still do not fully understand

- `settings = Settings()` runs at import. That is what makes bad config fail fast, but it also
  means importing anything from the app requires valid configuration. Does that ever get in
  the way of tests?
- `PostgresDsn` accepts a URL with no database name. Where would that surface?
- Production credentials clearly should not sit in `.env` on a server. What actually replaces
  it — Parameter Store, Secrets Manager, injected environment variables from the task
  definition?
- `SUPPORTED_CURRENCIES` is hardcoded in the service. It is a business rule today, but if it
  ever varies per customer, does it become configuration or database rows?

### One architecture decision I can now explain

**Why configuration belongs in the environment rather than in source.**

The tempting alternative is a `config_dev.py` and a `config_prod.py`, picking one at startup.
It is easy to write and easy to read. It also means the artifact that runs in production is
not the artifact that was tested in staging — the code differs, however slightly, and the
difference is exactly the part nobody exercised until it mattered.

Keeping configuration outside the code means one build runs everywhere. That becomes literal
rather than philosophical from Phase 27 onward: a container image is pushed to ECR once and
the *same digest* runs in dev and in production, differing only by the environment its task
definition supplies. An image containing `config_prod.py` cannot be that image.

The secrets argument follows from the same place. A credential in source is in the git
history forever, visible to everyone with read access, and rotating it means a commit and a
deploy. A credential in the environment is supplied at run time by something that can be
audited and rotated independently. `.env` being gitignored while `.env.example` is committed
splits those cleanly: the *names* of the settings are public documentation, the *values* are
not.

The honest limit: two of the three settings are declared but read by nothing. `.env.example`
labels them as such. There is a real tension with the rule applied in Phase 8, where an
uncalled repository method was left unwritten — the difference being that a config key with a
default is a documented knob rather than an untested code path, and enumerating the knobs is
what `.env.example` is *for*. Declaring the log level a phase before logging exists is a
smaller lie than shipping a method nothing has ever run.

### Interview questions I should be able to answer

1. Why should configuration come from the environment instead of a settings module per
   environment?
2. What is the precedence between an environment variable, a `.env` file, and a default?
3. Why validate configuration at startup rather than where it is used?
4. Why is `.env` gitignored while `.env.example` is committed?
5. How would you prove a configuration value actually reached the component it configures?
6. Where do production secrets live if not in `.env`?

---

## Phase 12 — Application Exceptions and Error Handling

### What I learned

**A domain error and a status code are two different things.** `app/core/exceptions.py`
contains three plain Python exceptions and mentions no HTTP anywhere:

```python
class DuplicateInvoiceError(InvoiceFlowError):
    def __init__(self, vendor: str, invoice_number: str): ...
```

"This invoice already exists" is true whether it arrived over HTTP, from a spreadsheet, or
out of a PDF. Only the HTTP case cares that the answer is `409`. That translation lives in
exactly one file, `app/core/error_handlers.py`, and nowhere else in the application knows both
halves.

**Exceptions carry data, not rendered messages.** `InvoiceValidationError` holds the issue
list; `DuplicateInvoiceError` holds the vendor and number. The HTTP layer builds a response
body from them, a bulk importer could build a report row, and Phase 13 can log structured
fields — all from the same object. A pre-formatted string would serve only the first.

**The tuple is gone.** Phase 9 was forced into this signature:

```python
def create(self, data) -> tuple[Invoice | None, list[dict]]:
```

because the service could raise neither `HTTPException` (framework coupling) nor a domain
exception (they did not exist). It now returns an `Invoice` and raises. The route became
exactly the line the playbook sketched three phases ago:

```python
def create_invoice(invoice: InvoiceCreate, service: InvoiceServiceDep):
    return service.create(invoice)
```

**The router stopped importing `HTTPException` entirely.** Verified by AST — its imported
names are now `APIRouter`, the two dependency aliases, the two schemas, and
`InvoiceNotFoundError`. The routes raise meaning; something else decides what meaning looks
like.

**Precedence between two error kinds had to be chosen deliberately.** An invoice can be both
malformed and a duplicate, and only one status can come back:

```text
bad currency + duplicate  ->  422 [INVALID_CURRENCY]
fix it, resubmit          ->  409 DUPLICATE_INVOICE
```

`422` wins because a duplicate of a malformed invoice is not a conflict — the data is simply
wrong, and the duplicate question does not become meaningful until it is fixed. Implemented by
moving the duplicate check out of `validate()` and into `create()`, after the rules.

**A side effect worth having: `validate()` became pure.** Six rules, no database, no I/O,
raises nothing. That is what Phase 20 will call on every spreadsheet row.

**The `500` from Phase 6 is closed.**

```text
before:  POST subtotal 99999999999.00  ->  500, empty body, cause only in the log
after:   POST subtotal 99999999999.00  ->  422 [AMOUNT_OUT_OF_RANGE]
```

`DataError` deliberately got no domain exception, because nothing in this codebase raises it —
it comes from the driver. It is handled in `error_handlers.py` because that module is already
the boundary between infrastructure and HTTP, which keeps SQLAlchemy out of both the service
and the router.

I also checked something the change could plausibly have broken: a `DataError` leaves its
transaction failed, so the next request could inherit a poisoned session. It does not —
overflow, then a valid create, then a list, all fine. Per-request sessions from Phase 10 are
why.

### Why this phase was needed

The service had no way to say "this failed, and here is why" that did not either drag FastAPI
into the business layer or make every caller remember to unpack a tuple. Meanwhile a duplicate
was reported as `422` when it is a conflict, and a database error reached clients as nothing
at all.

### What problem existed before it

`create()` returned `(invoice | None, issues)`. A caller writing
`invoice = service.create(data)` got a tuple and no error. The router decided every status
code inline. `DataError` escaped as an opaque `500`.

### New concepts

- Domain exceptions as distinct from transport errors
- A single translation layer, registered with `app.exception_handler`
- Exceptions carrying structured data rather than messages
- Deliberate precedence between error categories
- `409 Conflict` vs `422 Unprocessable Entity`
- Handling a third-party exception at the boundary rather than wrapping it

### Things I still do not fully understand

- Schema `422`s and business `422`s still have different body shapes. Overriding FastAPI's
  own validation handler would unify them — is that worth it, or is a client branching on
  `type` vs `code` acceptable?
- `InvoiceNotFoundError` is raised by the router, not the service, because reads bypass the
  service. Is that inconsistent, or just honest about where the check happens?
- There is no catch-all handler for genuinely unexpected exceptions. Should there be one that
  returns a scrubbed `500` and logs the detail — and is that Phase 13's or Phase 44's job?
- `DataError` is caught for amounts, but it covers other things too. Is `AMOUNT_OUT_OF_RANGE`
  claiming more than it knows?

### One architecture decision I can now explain

**Why the service layer must not be coupled to FastAPI's `HTTPException`.**

This phase answers the question Phase 9 could only pay for. Back then the service needed to
report failure and had exactly two options: raise `HTTPException`, or return a tuple. It
returned a tuple, and every caller has been unpacking it since.

Raising `HTTPException` would have been shorter and would have read better. The cost is that
"this invoice is invalid" and "the response status should be 422" become a single statement,
and the second half is only true when there is a response. Three phases on the roadmap have no
response: Phase 20 validates a thousand spreadsheet rows into a report; Phase 38 routes an
uncertain OCR extraction to human review; Phase 14 asserts that a future-dated invoice is
refused, without starting a server. A service that raises `HTTPException` serves none of them,
and the workaround — catching a web framework's exception in code that has no web request — is
worse than the tuple ever was.

The evidence is now concrete rather than theoretical. The Definition of Done asked that
service tests not depend on FastAPI HTTP exceptions, and the check ran every exception path —
validation failure, duplicate, precedence between the two, and a successful create — with
`sys.modules` containing **no `fastapi` module at all**, before or after.

What makes this affordable is that the coupling has to live *somewhere*, and the honest answer
is: in one file, at the edge. `error_handlers.py` knows about both domain errors and status
codes because translating between them is its entire job. Every other module knows one side
or the other. Swap HTTP for a queue consumer and exactly one file changes.

### Interview questions I should be able to answer

1. Why shouldn't a service layer raise `HTTPException`?
2. Where should the mapping from a domain error to a status code live?
3. What is the difference between `409` and `422`, and when does each apply?
4. An invoice is both malformed and a duplicate. Which error do you return, and why?
5. Why do these exceptions carry structured data instead of a formatted message?
6. A third-party library raises an exception your code never throws. Where do you handle it?
7. How would you prove that a service layer has no dependency on your web framework?

---

## Phase 13 — Logging

### What I learned

**The application was silent.** Before this phase the only output was uvicorn's access log:

```text
INFO: 127.0.0.1 - "POST /invoices HTTP/1.1" 422 Unprocessable Entity
```

That records *that* something was refused, never *why*, *which invoice*, or *which vendor*.
Counting application events in the log before the change: **zero**.

**Four events, logged where they happen.**

```text
INFO  invoice_created     invoice_id=1 invoice_number=LOG-1 vendor=ABC GmbH
INFO  invoice_rejected    invoice_number=LOG-2 vendor=ABC GmbH issue_codes=['INVALID_CURRENCY']
INFO  duplicate_detected  invoice_number=LOG-1 vendor=ABC GmbH
ERROR unexpected_error    path=/invoices method=GET exception_type=OperationalError
```

The first three come from the **service** because they are business facts, not HTTP facts —
the same events will appear when Phase 20's importer processes a spreadsheet with no request
involved. `unexpected_error` comes from an exception handler, because "a request blew up" is
inherently a request-boundary fact.

**Levels carry meaning, so they have to be chosen.** All three business events are `INFO`,
including rejections. A client sending an invalid invoice and being told so is a normal
outcome; logging it at `WARNING` would mean the level stops distinguishing anything.
`unexpected_error` is `ERROR` because it is a bug or an outage.

**`APP_ENV` finally does something.** It had been declared and unread since Phase 11 — the one
loose thread that phase left. It now picks the formatter: readable lines locally, one JSON
object per line everywhere else. And `LOG_LEVEL` does too — verified by running the same two
requests at `INFO` and at `WARNING`:

```text
LOG_LEVEL=INFO     invoice_created=1  invoice_rejected=1
LOG_LEVEL=WARNING  invoice_created=0  invoice_rejected=0
```

**Context goes in `extra={"context": {...}}`, not flat.** A flat `extra={"name": ...}` silently
collides with `LogRecord`'s own attributes — `message`, `args`, `name`, `module` are all
taken.

**stdout, not a file.** A container writes to its output stream and lets the platform decide
where that goes. Phase 29's Fargate tasks and Phase 44's CloudWatch both assume it.

### Two risks I checked instead of assuming

**Did the catch-all handler shadow the specific one?** Registering
`@app.exception_handler(Exception)` could plausibly swallow `DataError` and silently regress
Phase 12's `AMOUNT_OUT_OF_RANGE` back to a `500`. It does not — Starlette prefers the more
specific handler, and the amount overflow still returns `422`.

**Did clearing the root handlers break uvicorn's own logging?** No: startup lines present,
and four POSTs produced exactly four access lines — no duplication, no silence.

### Secrets, checked rather than claimed

The demonstration ran with `DATABASE_URL` containing the password `s3cr3t-p4ssw0rd`, then the
whole log was searched:

```text
s3cr3t-p4ssw0rd          occurrences: 0
invoiceflow:invoiceflow  occurrences: 0
postgresql+psycopg://    occurrences: 0
```

The same rule runs the other way. `unexpected_error` logs the full traceback and returns
`{"detail": "Internal server error"}` — an exception message can name a table, a column or a
connection string, and the person debugging has the log while the person who sent the request
does not need it.

### Why this phase was needed

The gap had already bitten twice in this project. In Phase 10 every request started returning
`500` and the cause — PostgreSQL had stopped — was only found by reading a raw traceback. In
Phase 6 a `DataError` reached the client as an empty `500` with the reason recorded nowhere
useful. Both are exactly what `unexpected_error` now captures; the demonstration for this
phase was in fact a replay of the Phase 10 incident.

### What problem existed before it

No record of what the application did or why anything was refused. Debugging meant reproducing
the problem locally, which does not work for something that happened in production an hour ago.

### New concepts

- Structured logging: events with fields rather than sentences
- Formatter selection by environment
- `extra=` and `LogRecord`'s reserved attribute names
- Log levels as a decision about what deserves attention
- Logging to stdout as a container contract
- The asymmetry between what is logged and what is returned

### Things I still do not fully understand

- Nothing ties log lines from one request together. A `request_id` would — is that Phase 44's
  job, or should it have been here?
- `logger.exception` inside an async handler: is the traceback capture safe if another
  exception is in flight?
- Phase 20 will validate thousands of rows. One `invoice_rejected` line per bad row could be
  tens of thousands of lines — does bulk work need a different logging strategy, or is that
  what sampling is for?
- The service now imports `logging`. That is stdlib rather than a framework, but it is still a
  dependency on an ambient global. Is passing a logger in ever worth it?

### One architecture decision I can now explain

**Why logs are events with fields rather than sentences.**

The natural thing to write is `logger.info(f"Rejected invoice {n} from {v}: bad currency")`.
It reads perfectly. It is also nearly useless at scale, because the only way to get anything
out of it is a regular expression over prose that some future edit will quietly break.

What was written instead is an event name and a bag of fields. The name is a stable
identifier — `invoice_rejected` means the same thing forever — and the fields are data, not
grammar. That difference is what makes the log queryable rather than merely readable:

```text
event = "invoice_rejected"           how many rejections
group by issue_codes                 which rule fires most
vendor = "ABC GmbH"                  everything one vendor sent
```

None of those questions can be answered by grepping sentences, and all three are things
someone actually asks when an import goes wrong.

It also determines whether Phase 44 is easy or painful. That phase wants
`invoice_validation_failures_total` as a metric — which, given events with a stable name and
structured fields, is a counter over `event = "invoice_rejected"`. Given sentences, it is a
second logging system bolted alongside the first.

The general shape: **a log line has two audiences, and only one of them is human.** Optimising
for the reader produces prose that no tool can use; optimising for the tool produces JSON that
is unpleasant to read at a terminal. Letting `APP_ENV` pick the formatter serves both without
either audience paying for the other — the same event, rendered for whoever is looking.

### Interview questions I should be able to answer

1. What is the difference between structured logging and just formatting a string?
2. Why log business events from the service rather than from the route handler?
3. Why is a validation failure `INFO` rather than `WARNING` or `ERROR`?
4. Why should a container log to stdout instead of a file?
5. What should never appear in a log, and what should never appear in a response?
6. How would you turn these logs into the metrics Phase 44 asks for?
7. Why does a catch-all `Exception` handler not break a more specific one?

---

## Phase 14 — Automated Testing Foundation

### What I learned

**Fifty tests in a third of a second, with one command.**

```text
$ uv run pytest
48 passed, 2 xfailed in 0.35s
```

Four categories, as the playbook asks: unit (pure rules), service (rules plus the database),
repository (real SQL), API (`TestClient`), plus two of my own — architecture rules, and a
concurrency case documenting a known gap.

**Transaction rollback as test isolation.** Each test gets a connection with an open
transaction that is rolled back afterwards:

```python
session = Session(bind=connection, join_transaction_mode="create_savepoint")
```

Without `create_savepoint` this would not work at all, because
`InvoiceRepository.create()` calls `session.commit()` — that commit would end the outer
transaction and leave nothing to roll back. With it, the session's commits release savepoints
and the outer rollback still undoes everything. The development database began with 5 rows,
ids 1–5, and had exactly the same 5 rows after every run.

**Rollback hides writes, not reads.** The first run failed with `assert 409 == 201`: the
default invoice number already existed among the pre-existing dev rows. Isolation from a
test's *own* writes says nothing about data that was committed before it started. The fix is
one line in the fixture — delete existing rows inside the transaction, so each test sees an
empty table and the rollback restores them.

**`dependency_overrides` earned its keep.** One line points the whole application at the
test's transaction:

```python
app.dependency_overrides[get_db] = lambda: db_session
```

Because `get_invoice_repository` and `get_invoice_service` both descend from `get_db`,
overriding the one redirects everything below it. Phase 10 built that chain deliberately; this
is the first time it was used for its actual purpose.

**Architecture rules can be tests.** Every phase since Phase 9 has ended with me manually
checking that the service imports no FastAPI. That check is now five assertions over the AST,
and it runs automatically.

### The most valuable thing I did was try to break it

A suite that has never failed is a suite of unknown value, so I deliberately broke three
things:

```text
1. remove GBP from SUPPORTED_CURRENCIES  ->  45 passed.  NOT CAUGHT.
2. make create() return a tuple again    ->  8 tests failed
3. reimport HTTPException in the router  ->  architecture test failed
```

Break 1 exposed a real hole. Every currency test asserted that *bad* values are rejected —
`XYZ`, `eur` — and none asserted that the supported ones are accepted. Deleting a currency
from the whitelist was invisible.

**Testing what a rule forbids says nothing about what it permits.** Adding
`test_supported_currencies_are_accepted` parametrized over EUR/USD/GBP closed it, and rerunning
break 1 then failed on `[GBP]` exactly as it should.

I would not have found that by writing more tests. I found it by asking what the tests would
fail to notice.

### Why this phase was needed

Every phase since Phase 1 was verified by replaying a `capture.py` battery by hand and diffing
it against the previous phase. That caught real problems — the Phase 5 docstring change, the
Phase 9 duplicate behavior — but it lived in a scratch directory, was never committed, needed a
running server, and required a human to read a diff.

It also settles a debt. Back in Phase 1 the playbook contradicted itself: §4.4 demands tests
every behavior-changing phase, while Phase 14 is where pytest arrives. We chose phase isolation
and verified manually on the understanding that this phase would pay it back. From Phase 15,
§4.4 applies normally.

### What problem existed before it

No committed tests. No way for anyone else to check the project works. No protection against
a regression except my own attention.

### New concepts

- pytest fixtures, composition, and `parametrize`
- Transaction rollback as isolation; `join_transaction_mode="create_savepoint"`
- `TestClient` and dependency overrides as a test seam
- `xfail(strict=True)` as executable documentation of a known defect
- Architecture rules expressed as assertions over the AST
- Mutation-style checking: break the code on purpose to measure the suite

### Things I still do not fully understand

- The suite shares one database with development. It works, but two `pytest` runs at once
  would collide. Is a separate test database the answer, or per-worker databases?
- `test_concurrency.py` really commits and cleans up in a `finally`. If it were killed
  mid-test it would leave rows behind. Is that acceptable for a test documenting a race?
- `TestClient` emits a deprecation warning about `httpx2`. Worth chasing now or later?
- Nothing measures coverage. Would that have found the currency hole, or would it have shown
  those lines as covered — since the rule *was* executed, just never with a passing value?

### One architecture decision I can now explain

**Why the tests were quick to write, and what that says about the earlier phases.**

`test_validation.py` constructs a service with **no repository at all**:

```python
service = InvoiceService(repository=None)
```

and tests fifteen rules against it. No database, no fixtures, no HTTP. That is only possible
because of two decisions made for entirely different reasons: Phase 9 moved the rules out of
the router so they did not need a request, and Phase 12 moved the duplicate check out of
`validate()` so it did not need a database.

Neither was made for testing. Phase 9's reason was that a rule needing the database could not
live in a router; Phase 12's was that a duplicate of a malformed invoice is not a conflict.
Testability came out as a by-product.

The same pattern holds throughout. The service can be tested without HTTP because Phase 12
gave it domain exceptions instead of `HTTPException`. The API can be tested without a real
database because Phase 10 built a dependency chain with a single override point. The
repository can be tested against real SQL in isolation because Phase 8 gave it a session
rather than letting it open one.

**Testability is not a feature you add; it is what code looks like when its dependencies point
in one direction and are supplied from outside.** The projects where tests are painful to
write are usually the ones where a function reaches out for what it needs — a global session,
a module-level config, a framework's request object — instead of being handed it. Every one of
those reaches was removed in an earlier phase for a reason that had nothing to do with
testing, and the bill for writing this suite came due at almost nothing.

Which is also the argument for why this phase comes at 14 and not at 1. Tests written in Phase
1 would have tested a Python list. Tests written now describe an architecture worth protecting.

### Interview questions I should be able to answer

1. How do you isolate tests that share a database without wiping it between runs?
2. What does `join_transaction_mode="create_savepoint"` solve?
3. Why did rolling back not stop pre-existing rows from breaking a test?
4. How would you point a FastAPI app's tests at a different database without editing routes?
5. What is `xfail(strict=True)` for, and why not just delete the test?
6. How do you know whether your test suite is any good?
7. Why is a rule that only tests rejection an incomplete test of that rule?
