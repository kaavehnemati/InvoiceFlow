# Deployment exercise: AWS Lightsail

**This is a learning exercise, not the production architecture.** The playbook says so
explicitly, and this document is written on that basis: the instance it describes was created,
verified, documented, and then deleted. Nothing here is running any more, which is exactly why
the real command output is reproduced rather than summarized — once the instance is gone, this
page is the only evidence the exercise happened.

What it proves: the application, packaged in Phase 23, runs unmodified on a machine that is not
the one it was built on, and answers requests from the public internet.

---

## What was deployed

| | |
| --- | --- |
| Region / AZ | `eu-central-1a` (Frankfurt) |
| Blueprint | `ubuntu_24_04` (OS only — no pre-installed application stack) |
| Bundle | 1 GB RAM, 2 vCPUs, 40 GB SSD (~$7/month in this region) |
| Instance name | `invoiceflow-lightsail` |
| Public address | `3.121.2.235` (static IP) |
| Exposed ports | `22/tcp` (SSH), `8000/tcp` (the API). Nothing else. |
| Reverse proxy | None — uvicorn is reached directly on port 8000 |
| TLS / domain | None — the Definition of Done is "publicly reachable", and a certificate needs a domain this exercise does not have |
| Database | PostgreSQL 16 in a container **on the same instance**, not a Lightsail managed database |

### Why 1 GB and not the cheaper tier

The cheapest bundle has 512 MB of RAM. Three containers start at once here — Postgres, the app,
and the one-shot migration container — plus a Docker image build on first boot. 512 MB invites
an out-of-memory kill during exactly the step that is hardest to debug remotely.

### Why the database is a container on the same instance

The alternative is a Lightsail managed database: a separate billable resource, its own
credentials, its own networking model. It is the more realistic production shape, and it is a
different thing to learn. This exercise is about the *instance* — so the database strategy is
the one that reuses Phase 23's `docker-compose.yml` byte for byte, and the whole application
stack stays one `docker compose up` exactly as it is locally.

---

## Machine setup

The instance was created through the Lightsail console (deliberately — the point was to see the
console's own model of instances, blueprints, bundles, static IPs and firewall rules before
automating any of it). The equivalent CLI commands are given at the bottom.

Bootstrapping is [`deploy/lightsail-bootstrap.sh`](../deploy/lightsail-bootstrap.sh), pasted
into the console's **launch script** field. It runs once, on first boot, as root:

```sh
apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker

git clone --branch feature/phase-24-lightsail --depth 1 https://github.com/kaavehnemati/InvoiceFlow.git /opt/invoiceflow

cd /opt/invoiceflow
docker compose -f docker-compose.yml -f docker-compose.lightsail.yml up -d
```

Nothing about the application is configured here. The instance installs Docker, fetches the
repository, and runs the same compose stack that runs on a laptop.

---

## Application process

`docker compose up -d` with two files layered:

```bash
docker compose -f docker-compose.yml -f docker-compose.lightsail.yml up -d
```

`docker-compose.yml` is unchanged from Phase 23. `docker-compose.lightsail.yml` carries only
what differs on a long-lived public VM:

| Override | Why |
| --- | --- |
| `restart: unless-stopped` on `db` and `app` | The stack must survive an instance reboot. Meaningless on a laptop you start and stop by hand. |
| `restart: "no"` on `migrate` | It is a one-shot command that is *supposed* to exit. Restarting it forever would be wrong. |
| `db`'s published port rebound to `127.0.0.1:5433` | See [exposed ports](#exposed-ports) below. |

Running state on the deployed instance:

```text
NAME                IMAGE             COMMAND                  SERVICE   STATUS                    PORTS
invoiceflow-app-1   invoiceflow-app   "uvicorn app.main:ap…"   app       Up About a minute         0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
invoiceflow-db-1    postgres:16       "docker-entrypoint.s…"   db        Up About a minute (healthy)  127.0.0.1:5433->5432/tcp
```

`migrate` does not appear because it had already exited `0` — the same shape verified locally in
Phase 23, now on a machine in Frankfurt.

---

## Environment variables

One variable matters, set in `docker-compose.yml` and unchanged for this deployment:

```text
DATABASE_URL=postgresql+psycopg://invoiceflow:invoiceflow@db:5432/invoiceflow
```

`db` is the Compose service name, resolved on the internal Compose network — the same string
that works locally works here, because nothing about it refers to a host.

**These are the same development credentials documented everywhere else in this project, and
they were reused deliberately.** That is defensible *only* because of the two conditions this
exercise satisfies: the database port is never reachable from outside the instance (verified
below, not assumed), and the instance was deleted immediately after the exercise. Neither
condition holds for a real deployment, and neither would excuse these credentials there —
Phase 41 and Phase 45 introduce secret storage for that reason.

---

## Exposed ports

| Port | Open to | Why |
| --- | --- | --- |
| `22/tcp` | the internet | SSH, needed to inspect and recover the instance |
| `8000/tcp` | the internet | the API — this is the Definition of Done |
| `5432` / `5433` | **nobody** | the database |

The default Lightsail firewall opens `22` and `80`. Port `80` was **removed** — nothing in this
stack listens on it, and an open port with nothing behind it is a claim you have to keep
explaining. Port `8000/tcp` was added for the API.

The database is protected by **two independent barriers**, not one:

1. The Lightsail firewall never opens `5433`, so packets do not reach the instance.
2. `docker-compose.lightsail.yml` binds the published port to `127.0.0.1` rather than
   `0.0.0.0`, so even if the firewall were opened later — by someone debugging, in a hurry,
   without reading this page — Postgres is still not listening on any address reachable from
   off the box.

Either alone would be sufficient today. Together, the failure that exposes the database has to
be two mistakes rather than one.

> The Compose override for this needs the `!override` merge tag:
> ```yaml
> ports: !override
>   - "127.0.0.1:5433:5432"
> ```
> Compose merges list-valued keys like `ports` by **appending**, so a plain override leaves the
> base file's `0.0.0.0:5433` mapping in place *alongside* the restricted one — publishing the
> database publicly while looking like it does the opposite. Verified directly with
> `docker compose config`, which showed both bindings until `!override` was added.

---

## Verification

### The API is publicly reachable

Checked from ~25 independent nodes worldwide via check-host.net against
`http://3.121.2.235:8000/` — every one returned `200 (OK)`:

```text
Austria, Vienna        OK   0.027 s   200 (OK)   3.121.2.235
Brazil, Sao Paulo      OK   0.418 s   200 (OK)   3.121.2.235
Bulgaria, Sofia        OK   0.068 s   200 (OK)   3.121.2.235
Canada, Vancouver      OK   0.292 s   200 (OK)   3.121.2.235
Cyprus, Larnaca        OK   0.111 s   200 (OK)   3.121.2.235
Finland, Helsinki      OK   0.055 s   200 (OK)   3.121.2.235
France, Paris          OK   0.020 s   200 (OK)   3.121.2.235
Germany, Frankfurt     OK   0.006 s   200 (OK)   3.121.2.235
Germany, Langen        OK   0.004 s   200 (OK)   3.121.2.235
Germany, Nuremberg     OK   0.011 s   200 (OK)   3.121.2.235
Hong Kong              OK   0.353 s   200 (OK)   3.121.2.235
India, Mumbai          OK   0.259 s   200 (OK)   3.121.2.235
Indonesia, Jakarta     OK   0.340 s   200 (OK)   3.121.2.235
Iran, Isfahan          OK   0.160 s   200 (OK)   3.121.2.235
Iran, Tehran           OK   0.163 s   200 (OK)   3.121.2.235
Israel, Tel Aviv       OK   0.118 s   200 (OK)   3.121.2.235
Italy, Milan           OK   0.021 s   200 (OK)   3.121.2.235
Japan, Tokyo           OK   0.495 s   200 (OK)   3.121.2.235
...
```

`/docs` — the interactive Swagger UI — answers from the same nodes, `200 (OK)` throughout:

```text
Austria, Vienna        OK   0.025 s   200 (OK)   3.121.2.235
Germany, Frankfurt     OK   0.006 s   200 (OK)   3.121.2.235
Canada, Vancouver      OK   0.292 s   200 (OK)   3.121.2.235
Japan, Tokyo           OK   0.489 s   200 (OK)   3.121.2.235
...
```

A third-party checker rather than a local `curl` was used on purpose — see
[the two false alarms](#two-false-alarms) below for why a single vantage point proved worthless
here.

### The database is *not* publicly reachable

The claim in [exposed ports](#exposed-ports) is worth exactly nothing unless it is tested, so
the same ~25 nodes were pointed at `3.121.2.235:5433`. **Every one of them failed, which is the
result this section wants:**

```text
Austria, Vienna        Connection timed out
Brazil, Sao Paulo      Connection timed out
Canada, Vancouver      Connection timed out
Germany, Frankfurt     Connection timed out
Germany, Nuremberg     Connection timed out
Hong Kong              Connection timed out
India, Mumbai          Connection timed out
Israel, Tel Aviv       Connection timed out
...
```

Same instance, same moment, same set of vantage points: port `8000` answers `200` from all of
them and port `5433` answers nothing from any of them. That is the difference between a
firewall you configured and a firewall you confirmed.

Note *timed out*, not *refused*: the packets are dropped before reaching the instance rather
than rejected by it — the Lightsail firewall doing its job at the network layer, with the
loopback binding sitting behind it as the second barrier that never had to be tested.

### The whole stack works, not just the banner route

`GET /` returns a static string and touches nothing. Creating an invoice exercises the app, the
database, and the migration that built its schema:

```console
$ curl -s -X POST http://localhost:8000/invoices -H "Content-Type: application/json" \
    -d '{"invoice_number":"LIGHTSAIL-1","vendor":"Frankfurt Test GmbH","invoice_date":"2026-01-15",
         "currency":"EUR","subtotal":"100.00","tax":"19.00","total":"119.00"}'

{"id":1,"invoice_number":"LIGHTSAIL-1","vendor":"Frankfurt Test GmbH",
 "invoice_date":"2026-01-15","currency":"EUR","subtotal":"100.00","tax":"19.00",
 "total":"119.00","status":"VALID","created_at":"2026-09-06T16:04:45.342072Z",
 "updated_at":"2026-09-06T16:04:45.342072Z","items":[]}
```

`id: 1` from a real sequence, `status: VALID` from the business rules, timestamps from the
database — on a schema that only exists because the `migrate` container ran on first boot.

---

## Two false alarms

Both cost real time, and both are worth recording because neither was a fault in the
application.

### 1. The launch script silently failed, under a shell nobody chose

The instance booted, and nothing was listening. `cloud-init status --long` gave:

```text
status: error
errors:
        - ('scripts_user', RuntimeError('Runparts: 1 failures (part-001) in 1 attempted commands'))
```

and one line in `/var/log/cloud-init-output.log` explained it:

```text
/var/lib/cloud/instance/scripts/part-001: 17: set: Illegal option -o pipefail
```

The script began `#!/bin/bash` and used `set -euo pipefail`. Pasted into the console's
launch-script field, the shebang did not survive as the literal first line of the saved script
(the reported line number is ~10 further in than the source file, so something was prepended
ahead of it), and cloud-init fell back to `/bin/sh` — dash — which has no `pipefail`. The
script aborted on its first line of real work, before Docker was installed.

The fix was not to fight the console. It was to stop depending on a shell this script never
needed: `#!/bin/sh` and `set -eu`, which behave identically in bash and dash. Nothing here pipes
commands together, so `pipefail` was never load-bearing — it was a habit, and the habit was the
bug.

### 2. Every reachability test was lying, in two different ways

After the stack was confirmed running — `curl localhost:8000/` returning `200` on the instance
in under a millisecond — it appeared unreachable from outside. Two separate causes, stacked:

**The testing environment had no real internet egress.** Its `curl` connected and then received
zero bytes; `nc` reported the port open; SSH died "during banner exchange". All three looked
like a server-side network fault. The giveaway was in the pings:

```text
ping 1.1.1.1       → 0.396 ms
ping github.com    → 0.550 ms
```

Sub-millisecond round trips to Cloudflare and GitHub are impossible. Something local was
completing handshakes on every destination's behalf and forwarding nothing. **Every measurement
taken from there was an artifact of the measuring instrument** — and one of them had already
been used to conclude "the deployment is broken."

**The address was stale.** Attaching a static IP *replaces* the instance's public address:
Lightsail assigns one from the static pool and releases the dynamic one. Every test up to that
point had been aimed at `18.153.59.47`, an address that no longer routed anywhere. Against the
real address, `3.121.2.235`, every one of ~25 global nodes returned `200 OK` immediately.

The lesson that generalizes: **a negative result from a single vantage point is not evidence of
anything.** "It doesn't work" was asserted twice from measurements that could not have worked
regardless of what the server did.

---

## Teardown

Lightsail bills per hour from creation. Both instances from this exercise — the console-created
one and the CLI-created one — were proven and then deleted, along with their static IPs and key
pairs:

```bash
aws lightsail delete-instance   --instance-name invoiceflow-lightsail-cli
aws lightsail release-static-ip --static-ip-name invoiceflow-lightsail-cli-ip
aws lightsail delete-key-pair   --key-pair-name  invoiceflow-lightsail-key
```

A static IP that is allocated but **not attached to anything** is billed, unlike one in use —
this bit once already: the console instance was deleted in an earlier step of this exercise,
its static IP was left behind, allocated and unattached, and only found and released while
setting up the CLI half. Confirmed clean at the end, for both instances:

```console
$ aws lightsail get-instances --query 'instances[].name' --output text
$ aws lightsail get-static-ips --query 'staticIps[].name' --output text
$ aws lightsail get-key-pairs --query 'keyPairs[?name==`invoiceflow-lightsail-key`].name' --output text
```

All three empty.

---

## The same thing via the CLI

The console was used deliberately, to see Lightsail's own model of these resources first. The
CLI version below was then actually run — a second instance, `invoiceflow-lightsail-cli` — for
two reasons: to have a documented, reproducible version of this deployment rather than only a
sequence of clicks, and to prove the bootstrap-script fix from [the first false
alarm](#two-false-alarms) actually holds when the script is read from a file instead of pasted
into a textarea.

It did. `--user-data file://deploy/lightsail-bootstrap.sh` sends the script's bytes exactly as
they sit on disk — no console field to mangle a shebang — and this time cloud-init reported:

```console
$ ssh -i invoiceflow-lightsail-key.pem ubuntu@<ip> "cloud-init status --long"
status: done
extended_status: done
errors: []
recoverable_errors: {}
```

`done`, zero errors, on the first boot, with no manual recovery step. `docker compose ps`
moments later, unprompted:

```text
NAME                IMAGE             COMMAND                  SERVICE   STATUS
invoiceflow-app-1   invoiceflow-app   "uvicorn app.main:ap…"   app       Up 5 minutes
invoiceflow-db-1    postgres:16       "docker-entrypoint.s…"   db        Up 5 minutes (healthy)
```

And the same third-party check against the new instance's address, `3.122.3.155` — every node
`200 (OK)`, confirming the CLI-provisioned instance is exactly as reachable as the
console-provisioned one was, with none of the console's paste-related fragility:

```text
Austria, Vienna        OK   0.064 s   200 (OK)   3.122.3.155
Germany, Frankfurt     OK   0.080 s   200 (OK)   3.122.3.155
Iran, Tehran           OK   0.145 s   200 (OK)   3.122.3.155
Japan, Tokyo           OK   0.513 s   200 (OK)   3.122.3.155
...
```

The commands that produced it, for reference and reuse:

```bash
# 1. a key pair to SSH with; the private key is returned once, and only once
aws lightsail create-key-pair --key-pair-name invoiceflow-lightsail-key \
  --region eu-central-1 --query 'privateKeyBase64' --output text > invoiceflow-lightsail.pem
chmod 600 invoiceflow-lightsail.pem

# 2. the instance, bootstrapped by the launch script
aws lightsail create-instances \
  --instance-names invoiceflow-lightsail \
  --availability-zone eu-central-1a \
  --blueprint-id ubuntu_24_04 \
  --bundle-id micro_3_0 \
  --key-pair-name invoiceflow-lightsail-key \
  --user-data file://deploy/lightsail-bootstrap.sh \
  --region eu-central-1

# 3. a stable address -- note this REPLACES the instance's public IP
aws lightsail allocate-static-ip --static-ip-name invoiceflow-lightsail-ip --region eu-central-1
aws lightsail attach-static-ip   --static-ip-name invoiceflow-lightsail-ip \
  --instance-name invoiceflow-lightsail --region eu-central-1

# 4. exactly two ports open; note this REPLACES the whole rule set, closing port 80
aws lightsail put-instance-public-ports \
  --instance-name invoiceflow-lightsail \
  --port-infos fromPort=22,toPort=22,protocol=TCP fromPort=8000,toPort=8000,protocol=TCP \
  --region eu-central-1

# 5. the address to actually test against
aws lightsail get-instance --instance-name invoiceflow-lightsail \
  --region eu-central-1 --query 'instance.publicIpAddress' --output text
```

Two of those commands replace rather than add, which is worth knowing before running them:
`attach-static-ip` changes the public address out from under anything already using the old
one, and `put-instance-public-ports` sets the complete firewall rule set — the port `80` rule
disappears because it is not listed, not because it was deleted.
