#!/usr/bin/env python3
"""隔离模式下的测试入口：显式注入项目根后调用 unittest。

`python -I` 会忽略 PYTHONPATH 与当前目录，直接 discover 时找不到 workbench 包，
因此用本脚本把项目根放进 sys.path（数据目录仍由测试夹具自行管理）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
