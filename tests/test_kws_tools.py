import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_wake_keyword = _load_script("build_wake_keyword.py")
kws_sweep = _load_script("kws_sweep.py")


class KeywordToolTests(unittest.TestCase):
    def test_keyword_tokens_excludes_kws_metadata(self):
        line = "小 西 小 西 :2.5 #0.25 @小西小西"
        self.assertEqual(
            build_wake_keyword.keyword_tokens(line),
            ["小", "西", "小", "西"],
        )

    def test_sweep_base_keyword_ignores_existing_parameter_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "keywords.txt"
            path.write_text(
                "小 西 小 西 :1.5 #0.35 @小西小西\n",
                encoding="utf-8",
            )
            self.assertEqual(kws_sweep._base_keyword_line(path), "小 西 小 西")

    def test_parse_floats_accepts_parameter_matrix_syntax(self):
        self.assertEqual(
            kws_sweep._parse_floats("1.5, 2.0,2.5,3.0"),
            [1.5, 2.0, 2.5, 3.0],
        )


if __name__ == "__main__":
    unittest.main()
