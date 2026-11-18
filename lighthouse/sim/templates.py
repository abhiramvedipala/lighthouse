"""Fixed log templates per service (the simulator's ground truth for the parser).

Placeholders in braces are filled with random variable fields by logs.py:
{ip} {ms} {id} {sku} {uuid} {n} {hex} {user} {host} {order}.
Categories: info (misc INFO), warn, err_base (baseline errors), err_up
(upstream/dependency errors), err_novel (appears only during novel_error faults).
`err_base` templates carry a deploy variant: the same event reworded, which is
what a deploy looks like to a template miner.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    tid: str
    level: str
    category: str
    fmt: str
    exc: str = ""          # exception class mentioned in the message, if any
    variant: str = ""      # reworded text used while a deploy is active


def _mk(svc: str, level: str, category: str, items: list, exc: bool = False) -> list[Template]:
    out = []
    for i, it in enumerate(items):
        fmt, ex, var = (it, "", "") if isinstance(it, str) else (it + ("", ""))[:3]
        out.append(Template(f"{svc}.{category}.{i:02d}", level, category, fmt, ex, var))
    return out


GATEWAY = (
    _mk("gateway", "INFO", "info", [
        "cache hit for key products:{id} age={ms}ms",
        "cache refreshed for key products:{id} entries={n}",
        "session started user={user} ip={ip}",
        "session expired user={user} idle={n}s",
        "route table reloaded routes={n} version={hex}",
        "upstream pool healthy orders connections={n}",
        "upstream pool healthy inventory connections={n}",
        "rate limiter window rolled bucket={hex} remaining={n}",
        "checkout started cart={id} items={n}",
        "checkout completed cart={id} order={order} total={n}",
        "auth token validated user={user} ttl={n}s",
        "config reloaded revision={hex}",
        "health check ok uptime={n}s",
        "tls handshake completed client={ip} version=1.3",
        "response compressed bytes={n} ratio={n}",
    ])
    + _mk("gateway", "WARN", "warn", [
        "cache miss for key products:{id} falling back to origin",
        "retrying upstream call to orders attempt={n} after {ms}ms",
        "retrying upstream call to inventory attempt={n} after {ms}ms",
        "slow upstream response from orders took {ms}ms",
        "slow upstream response from inventory took {ms}ms",
        "rate limit approaching client={ip} used={n} of 100",
        "connection pool near capacity in_use={n} max=64",
        "request body larger than expected bytes={n}",
        "deprecated header X-Legacy-Id received from {ip}",
        "slow tls handshake client={ip} took {ms}ms",
    ])
    + _mk("gateway", "ERROR", "err_base", [
        ("upstream orders returned 500 for cart={id} HTTPStatusError", "HTTPStatusError", "orders call failed with status 500 cart={id} HTTPStatusError"),
        ("failed to serialize response for key products:{id} ValueError", "ValueError", "response serialization failed key=products:{id} ValueError"),
        ("client disconnected before response ip={ip} ConnectionResetError", "ConnectionResetError", "client connection reset ip={ip} ConnectionResetError"),
        ("request timed out after {ms}ms cart={id} TimeoutError", "TimeoutError", "deadline exceeded after {ms}ms cart={id} TimeoutError"),
        ("invalid cart state cart={id} state={n} RuntimeError", "RuntimeError", "cart state invalid cart={id} state={n} RuntimeError"),
        ("auth backend unavailable user={user} ConnectionError", "ConnectionError", "auth service unreachable user={user} ConnectionError"),
    ])
    + _mk("gateway", "ERROR", "err_up", [
        "upstream orders unavailable 503 cart={id} ServiceUnavailableError",
        "circuit open for orders after {n} failures",
        "upstream inventory unavailable 503 sku={sku} ServiceUnavailableError",
        "upstream pool exhausted for orders waiting={n}",
    ])
    + _mk("gateway", "ERROR", "err_novel", [
        "payment token rejected cart={id} code={n} PaymentDeclinedError",
    ])
)

ORDERS = (
    _mk("orders", "INFO", "info", [
        "order created order={order} user={user} items={n}",
        "order confirmed order={order} total={n}",
        "order fetched order={order} from cache",
        "order fetched order={order} from database",
        "inventory reserved order={order} lines={n}",
        "payment authorised order={order} ref={hex}",
        "database connection acquired wait={ms}ms",
        "database connection released held={ms}ms",
        "batch flush completed rows={n} took={ms}ms",
        "queue depth sampled depth={n}",
        "idempotency key stored key={uuid}",
        "idempotency key replayed key={uuid}",
        "config reloaded revision={hex}",
        "health check ok uptime={n}s",
        "scheduled cleanup removed {n} stale carts",
    ])
    + _mk("orders", "WARN", "warn", [
        "retrying inventory reserve order={order} attempt={n} after {ms}ms",
        "slow database query took {ms}ms rows={n}",
        "database connection pool near capacity in_use={n} max=20",
        "order total mismatch order={order} expected={n} got={n}",
        "idempotency key collision key={uuid}",
        "slow inventory response took {ms}ms order={order}",
        "payment provider latency high {ms}ms",
        "queue depth above soft limit depth={n}",
        "stale cache entry for order={order} age={n}s",
        "retrying database commit attempt={n} after {ms}ms",
    ])
    + _mk("orders", "ERROR", "err_base", [
        ("database timeout after {ms}ms order={order} OperationalError", "OperationalError", "db query exceeded {ms}ms order={order} OperationalError"),
        ("order not found order={order} NotFoundError", "NotFoundError", "no such order order={order} NotFoundError"),
        ("failed to reserve stock for order={order} sku={sku} StockError", "StockError", "stock reservation failed order={order} sku={sku} StockError"),
        ("payment declined order={order} code={n} PaymentError", "PaymentError", "payment refused order={order} code={n} PaymentError"),
        ("deadlock detected order={order} retry={n} DeadlockError", "DeadlockError", "transaction deadlock order={order} retry={n} DeadlockError"),
        ("serialization failure order={order} IntegrityError", "IntegrityError", "integrity violation order={order} IntegrityError"),
    ])
    + _mk("orders", "ERROR", "err_up", [
        "inventory service returned 503 order={order} ServiceUnavailableError",
        "circuit open for inventory after {n} failures",
        "inventory call timed out after {ms}ms order={order} TimeoutError",
        "upstream pool exhausted for inventory waiting={n}",
    ])
    + _mk("orders", "ERROR", "err_novel", [
        "ledger write rejected order={order} version={n} LedgerConflictError",
    ])
)

INVENTORY = (
    _mk("inventory", "INFO", "info", [
        "stock level read sku={sku} qty={n}",
        "stock reserved sku={sku} qty={n} order={order}",
        "stock released sku={sku} qty={n}",
        "restock received sku={sku} qty={n} supplier={n}",
        "cache hit for sku={sku} age={ms}ms",
        "cache refreshed sku={sku} qty={n}",
        "warehouse sync completed items={n} took={ms}ms",
        "index rebuilt shard={n} docs={n}",
        "database connection acquired wait={ms}ms",
        "database connection released held={ms}ms",
        "low stock flagged sku={sku} qty={n}",
        "price lookup sku={sku} cents={n}",
        "config reloaded revision={hex}",
        "health check ok uptime={n}s",
        "snapshot written bytes={n} took={ms}ms",
    ])
    + _mk("inventory", "WARN", "warn", [
        "cache miss for sku={sku} falling back to database",
        "slow database query took {ms}ms rows={n}",
        "stock level negative sku={sku} qty={n} clamped to 0",
        "warehouse sync lagging by {n}s",
        "database connection pool near capacity in_use={n} max=20",
        "retrying database read attempt={n} after {ms}ms",
        "unknown sku requested sku={sku}",
        "reservation near expiry sku={sku} ttl={n}s",
        "index shard slow shard={n} took {ms}ms",
        "stale snapshot detected age={n}s",
    ])
    + _mk("inventory", "ERROR", "err_base", [
        ("database timeout after {ms}ms sku={sku} OperationalError", "OperationalError", "db read exceeded {ms}ms sku={sku} OperationalError"),
        ("sku not found sku={sku} NotFoundError", "NotFoundError", "no such sku sku={sku} NotFoundError"),
        ("reservation conflict sku={sku} order={order} ConflictError", "ConflictError", "reservation clash sku={sku} order={order} ConflictError"),
        ("warehouse feed parse failure line={n} ParseError", "ParseError", "warehouse feed unreadable line={n} ParseError"),
        ("snapshot write failed path=/var/snap/{hex} OSError", "OSError", "snapshot could not be written path=/var/snap/{hex} OSError"),
    ])
    + _mk("inventory", "ERROR", "err_up", [
        "database unavailable 503 sku={sku} ServiceUnavailableError",
        "storage backend refused connection host={host} ConnectionRefusedError",
        "replica lag too high lag={n}s refusing reads",
        "worker pool exhausted waiting={n}",
    ])
    + _mk("inventory", "ERROR", "err_novel", [
        "checksum mismatch in stock shard={n} expected={hex} got={hex} CorruptionError",
    ])
)

# Request lines: one per endpoint, always INFO.
REQUEST = {
    ("gateway", "GET /products"): "request handled GET /products status={status} latency_ms={ms} client={ip}",
    ("gateway", "POST /checkout"): "request handled POST /checkout status={status} latency_ms={ms} cart={id}",
    ("orders", "POST /orders"): "request handled POST /orders status={status} latency_ms={ms} order={order}",
    ("orders", "GET /orders/{id}"): "request handled GET /orders/{order} status={status} latency_ms={ms}",
    ("inventory", "GET /stock/{sku}"): "request handled GET /stock/{sku} status={status} latency_ms={ms}",
}

TEMPLATES: dict[str, list[Template]] = {"gateway": GATEWAY, "orders": ORDERS, "inventory": INVENTORY}


def by_category(service: str, category: str) -> list[Template]:
    return [t for t in TEMPLATES[service] if t.category == category]


def request_template_id(service: str, endpoint: str) -> str:
    return f"{service}.req.{endpoint.replace(' ', '_')}"


DEPLOY = {
    s: Template(f"{s}.deploy.00", "INFO", "deploy", "deploy rolling restart version={hex} pod={n}")
    for s in TEMPLATES
}


def truth_template(fmt: str) -> str:
    """Ground-truth template: every placeholder becomes <*>, as in Loghub."""
    import re

    return re.sub(r"\{[a-z]+\}", "<*>", fmt)
