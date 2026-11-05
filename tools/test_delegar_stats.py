"""Contrato de tools/delegar_stats.py (escrito pelo arquiteto; a implementação foi delegada)."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.delegar_stats import load, summarize

RECORDS = [
    {"status": "OK", "seconds": 100.0, "retry": False, "verify_exit": 0,
     "tokens": {"input": 1000, "output": 200, "reasoning": 300}},
    {"status": "FALHOU", "seconds": 50.5, "retry": False, "verify_exit": 1,
     "tokens": {"input": 500, "output": 100, "reasoning": 0}},
    {"status": "OK", "seconds": 20.0, "retry": True, "verify_exit": 0,
     "tokens": {"input": 300, "output": 50, "reasoning": 10}},
    {"status": "TIMEOUT", "seconds": 1800.0, "retry": False, "verify_exit": None, "tokens": {}},
]


class TestSummarize(unittest.TestCase):
    def test_counts(self):
        s = summarize(RECORDS)
        self.assertEqual(s["runs"], 4)
        self.assertEqual(s["retries"], 1)
        self.assertEqual(s["verify_ok"], 2)
        self.assertEqual(s["verify_fail"], 1)
        self.assertEqual(s["by_status"], {"OK": 2, "FALHOU": 1, "TIMEOUT": 1})

    def test_totals(self):
        s = summarize(RECORDS)
        self.assertAlmostEqual(s["total_seconds"], 1970.5)
        self.assertEqual(s["executor_input_tokens"], 1800)
        # saída do executor = output + reasoning (é o que o Opus deixou de gerar)
        self.assertEqual(s["executor_output_tokens"], 660)

    def test_success_rate(self):
        # verify_ok / execuções que tiveram verificação (verify_exit não-nulo)
        self.assertAlmostEqual(summarize(RECORDS)["success_rate"], 2 / 3)

    def test_empty(self):
        s = summarize([])
        self.assertEqual(s["runs"], 0)
        self.assertEqual(s["success_rate"], 0.0)
        self.assertEqual(s["by_status"], {})

    def test_missing_keys_do_not_crash(self):
        s = summarize([{}])
        self.assertEqual(s["runs"], 1)
        self.assertEqual(s["executor_output_tokens"], 0)
        self.assertEqual(s["by_status"], {"?": 1})


class TestLoad(unittest.TestCase):
    def test_skips_blank_and_invalid_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            p.write_text(json.dumps(RECORDS[0]) + "\n\nnão é json\n" + json.dumps(RECORDS[1]) + "\n",
                         encoding="utf-8")
            self.assertEqual(load(p), RECORDS[:2])

    def test_missing_file_is_empty(self):
        self.assertEqual(load(Path("nao/existe.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
