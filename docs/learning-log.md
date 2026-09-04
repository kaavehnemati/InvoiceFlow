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
