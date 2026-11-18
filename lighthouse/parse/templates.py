"""Template mining (Drain3), the regex+exact baseline, and error signatures.

`TemplateStore` wraps a Drain3 `TemplateMiner` with persisted state so a streaming
consumer that restarts, or a batch run split in two, assigns the same template ids
as one uninterrupted pass over the same lines.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.template_miner_config import TemplateMinerConfig

ROOT = Path(__file__).resolve().parents[2]
DRAIN_INI = ROOT / "config" / "drain3.ini"

EXC_RE = re.compile(r"\b((?:[a-z_]\w*\.)*[A-Z]\w*(?:Error|Exception))\b")


def load_config(ini: Path | str | None = None, sim_th: float | None = None, depth: int | None = None):
    cfg = TemplateMinerConfig()
    cfg.load(str(ini or DRAIN_INI))
    if sim_th is not None:
        cfg.drain_sim_th = sim_th
    if depth is not None:
        cfg.drain_depth = depth
    cfg.profiling_enabled = False
    return cfg


class TemplateStore:
    """Drain3 with optional file persistence. `add` returns a stable integer template id."""

    def __init__(self, state_path: Path | str | None = None, ini: Path | str | None = None, **overrides):
        self.state_path = Path(state_path) if state_path else None
        handler = FilePersistence(str(self.state_path)) if self.state_path else None
        self.miner = TemplateMiner(handler, load_config(ini, **overrides))

    def add(self, message: str) -> int:
        return int(self.miner.add_log_message(message)["cluster_id"])

    def match(self, message: str) -> int | None:
        """Template id without learning anything new (None if no template fits)."""
        c = self.miner.match(message, full_search_strategy="fallback")
        return None if c is None else int(c.cluster_id)

    def template(self, cluster_id: int) -> str:
        for c in self.miner.drain.clusters:
            if c.cluster_id == cluster_id:
                return c.get_template()
        raise KeyError(cluster_id)

    def templates(self) -> dict[int, str]:
        return {int(c.cluster_id): c.get_template() for c in self.miner.drain.clusters}

    def save(self) -> None:
        if self.state_path:
            self.miner.save_state("lighthouse")


def drain_parser(sim_th: float | None = None, depth: int | None = None):
    def parse(lines: Sequence[str]) -> list[int]:
        store = TemplateStore(sim_th=sim_th, depth=depth)
        return [store.add(x) for x in lines]

    return parse


def _mask_regexes(ini: Path | str | None = None) -> list[tuple[re.Pattern, str]]:
    cfg = load_config(ini)
    return [(m.regex, f"<{m.mask_with}>") for m in cfg.masking_instructions]


def regex_exact_parser(ini: Path | str | None = None):
    """Baseline: mask variables with the same regexes as Drain, then group identical strings."""
    masks = _mask_regexes(ini)

    def parse(lines: Sequence[str]) -> list[int]:
        ids: dict[str, int] = {}
        out = []
        for line in lines:
            for rx, rep in masks:
                line = rx.sub(rep, line)
            out.append(ids.setdefault(line, len(ids)))
        return out

    return parse


PARSERS = {"drain3": drain_parser(), "regex_exact": regex_exact_parser()}


@dataclass(frozen=True)
class Signature:
    service: str
    template_id: int
    exception: str

    def key(self) -> str:
        return f"{self.service}|{self.template_id}|{self.exception}"


def exception_class(message: str) -> str:
    m = EXC_RE.search(message)
    return m.group(1) if m else ""


class SignatureBook:
    """Error signatures with first-seen time. Only ever looks at the past."""

    def __init__(self):
        self.first_seen: dict[str, int] = {}  # key -> epoch ms

    def observe(self, service: str, template_id: int, message: str, ts_ms: int) -> tuple[Signature, bool]:
        sig = Signature(service, template_id, exception_class(message))
        k = sig.key()
        new = k not in self.first_seen
        if new:
            self.first_seen[k] = ts_ms
        return sig, new

    def new_since(self, ts_ms: int, hours: float = 24.0) -> list[str]:
        """Signatures first seen within `hours` before ts_ms (inclusive of ts_ms)."""
        lo = ts_ms - int(hours * 3_600_000)
        return [k for k, t in self.first_seen.items() if lo <= t <= ts_ms]

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.first_seen))

    @classmethod
    def load(cls, path: Path | str) -> SignatureBook:
        b = cls()
        p = Path(path)
        if p.exists():
            b.first_seen = {k: int(v) for k, v in json.loads(p.read_text()).items()}
        return b
