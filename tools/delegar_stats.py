"""Resumo das métricas de delegação gravadas em logs/delegar.jsonl (uma linha JSON por execução)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "delegar.jsonl"


def load(path: Path) -> list[dict]:
    """Lê JSONL em UTF-8; pula linhas vazias e que não são JSON; arquivo inexistente vira []."""
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def summarize(records: list[dict]) -> dict:
    """Agrega as métricas das delegações; chaves ausentes valem zero/None, nunca levantam exceção."""
    verify_ok = sum(1 for r in records if r.get("verify_exit") == 0)
    verify_fail = sum(1 for r in records if r.get("verify_exit") is not None and r.get("verify_exit") != 0)
    checked = verify_ok + verify_fail
    by_status: dict[str, int] = {}
    for r in records:
        status = r.get("status")
        key = status if status is not None else "?"
        by_status[key] = by_status.get(key, 0) + 1

    tokens = [r.get("tokens") or {} for r in records]
    return {
        "runs": len(records),
        "retries": sum(1 for r in records if r.get("retry")),
        "verify_ok": verify_ok,
        "verify_fail": verify_fail,
        "success_rate": verify_ok / checked if checked else 0.0,
        "total_seconds": sum(r.get("seconds") or 0 for r in records),
        "executor_input_tokens": sum(t.get("input") or 0 for t in tokens),
        "executor_output_tokens": sum((t.get("output") or 0) + (t.get("reasoning") or 0) for t in tokens),
        "by_status": by_status,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    records = load(LOG_PATH)
    s = summarize(records)
    print(f"delegações: {s['runs']} (retries: {s['retries']})")
    print(f"verificação: {s['verify_ok']} ok, {s['verify_fail']} falha, taxa de sucesso: {s['success_rate']:.1%}")
    print(f"tempo total: {s['total_seconds']:.1f} s")
    print(f"tokens do executor: entrada {s['executor_input_tokens']}, saída {s['executor_output_tokens']}")
    print("por status: " + (", ".join(f"{k}×{v}" for k, v in sorted(s["by_status"].items())) or "nenhum"))


if __name__ == "__main__":
    main()
