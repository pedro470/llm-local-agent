"""Contrato das funções puras de tools/delegar.py: parse_status e changed_files."""

import unittest

from tools.delegar import changed_files, parse_status


class TestParseStatus(unittest.TestCase):
    def test_report_normal(self):
        text = "STATUS: OK\nARQUIVOS: a.py, b.py\nVERIFICACAO: passou\nNOTAS: sem mais"
        self.assertEqual(parse_status(text), "OK")

    def test_two_status_lines_take_last(self):
        text = "STATUS: BLOQUEADO\npergunta ao arquiteto...\nSTATUS: FALHOU"
        self.assertEqual(parse_status(text), "FALHOU")

    def test_lowercase_status(self):
        self.assertEqual(parse_status("status: ok"), "ok")

    def test_empty_text(self):
        self.assertEqual(parse_status(""), "SEM RELATÓRIO")

    def test_no_status_line(self):
        self.assertEqual(parse_status("feito\nsem linha de status aqui\nok"), "SEM RELATÓRIO")

    def test_leading_spaces_and_trailing_stripped(self):
        text = "  STATUS:    FALHOU   \nNOTAS: x"
        self.assertEqual(parse_status(text), "FALHOU")


class TestChangedFiles(unittest.TestCase):
    def test_new_file(self):
        self.assertEqual(changed_files({}, {"a.py": "h1"}), ["a.py"])

    def test_dirty_before_and_changed(self):
        self.assertEqual(changed_files({"a.py": "h1"}, {"a.py": "h2"}), ["a.py"])

    def test_dirty_before_and_untouched(self):
        # mesmo hash nos dois lados: o executor não mexeu, não aparece
        self.assertEqual(changed_files({"a.py": "h1"}, {"a.py": "h1"}), [])

    def test_dirty_before_reverted(self):
        # sujo antes e sumiu de after: o executor reverteu para o estado do repositório
        self.assertEqual(changed_files({"a.py": "h1"}, {}), ["a.py"])

    def test_order_modified_then_removed_sorted(self):
        before = {"z.py": "1", "m.py": "2", "r.py": "3"}
        after = {"b.py": "9", "z.py": "novo", "a.py": "novo"}
        # mudados/novos ordenados (after) primeiro, depois os removidos ordenados
        self.assertEqual(changed_files(before, after), ["a.py", "b.py", "z.py", "m.py", "r.py"])

    def test_empty_both(self):
        self.assertEqual(changed_files({}, {}), [])


if __name__ == "__main__":
    unittest.main()
