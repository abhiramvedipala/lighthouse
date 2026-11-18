"""Parser benchmark: grouping accuracy and template counts against ground truth.

Grouping accuracy is the Loghub definition: a line is correct only if the whole
predicted group has exactly the same lines as its ground-truth group. It is
strict: one stray line in a group costs the entire group.

    uv run python -m lighthouse.parse.bench --all
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LOGHUB_DIR = ROOT / "data" / "loghub"
LOGHUB_SETS = ("HDFS", "BGL", "OpenStack", "Apache")

Parser = Callable[[Sequence[str]], Sequence]


def grouping_accuracy(truth: Sequence, pred: Sequence) -> float:
    """Share of lines whose predicted group equals their true group exactly."""
    if len(truth) != len(pred):
        raise ValueError("truth and pred must have the same length")
    if len(truth) == 0:
        return 0.0
    df = pd.DataFrame({"t": list(truth), "p": list(pred)})
    truth_size = df.groupby("t").size()
    g = df.groupby("p")["t"].agg(["nunique", "first", "size"])
    ok = g[(g["nunique"] == 1) & (g["size"].to_numpy() == truth_size.loc[g["first"]].to_numpy())]
    return float(ok["size"].sum() / len(df))


def template_counts(truth: Sequence, pred: Sequence) -> tuple[int, int]:
    """(templates found, templates in the ground truth)."""
    return len(set(pred)), len(set(truth))


def load_loghub(name: str, data_dir: Path | None = None) -> pd.DataFrame:
    path = (data_dir or LOGHUB_DIR) / f"{name}_2k.log_structured.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run scripts/get_data.sh")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def evaluate_parser(parser: Parser, contents: Sequence[str], truth: Sequence) -> dict:
    t0 = time.perf_counter()
    pred = parser(contents)
    secs = time.perf_counter() - t0
    found, true_n = template_counts(truth, pred)
    return {
        "grouping_accuracy": round(grouping_accuracy(truth, pred), 4),
        "templates_found": found,
        "templates_true": true_n,
        "seconds": round(secs, 3),
    }


def registry() -> dict[str, Parser]:
    """Name -> parser. Parsers register themselves in lighthouse.parse.templates."""
    reg: dict[str, Parser] = {"exact": lambda lines: list(lines)}  # every distinct line its own group
    try:
        from lighthouse.parse import templates

        reg.update(templates.PARSERS)
    except ImportError:
        pass
    return reg


def run_all(names: Sequence[str] = LOGHUB_SETS) -> pd.DataFrame:
    rows = []
    for ds in names:
        df = load_loghub(ds)
        for pname, fn in registry().items():
            r = evaluate_parser(fn, df["Content"].tolist(), df["EventId"].tolist())
            rows.append({"dataset": ds, "parser": pname, **r})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="all four Loghub samples")
    ap.add_argument("--dataset", choices=LOGHUB_SETS)
    a = ap.parse_args()
    names = LOGHUB_SETS if a.all or not a.dataset else (a.dataset,)
    print(run_all(names).to_string(index=False))


if __name__ == "__main__":
    main()
