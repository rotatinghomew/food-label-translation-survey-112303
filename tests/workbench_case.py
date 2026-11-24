"""工作台共享测试夹具：把合成数据复制到临时目录，测试互不污染。"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workbench.cli import run_pipeline  # noqa: E402
from workbench.io import load_survey  # noqa: E402

DATA = ROOT / "data"
TODAY = "2026-10-14"


class WorkbenchCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name) / "data"
        shutil.copytree(DATA, self.tmpdir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def load(self, **kwargs):
        return load_survey(self.tmpdir, **kwargs)

    def pipeline(self):
        return run_pipeline(self.tmpdir, TODAY)

    def write_csv(self, name: str, header: list[str], rows: list[list[str]]) -> None:
        import csv

        with (self.tmpdir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, strict=True)
            writer.writerow(header)
            writer.writerows(rows)
