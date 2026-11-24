#!/usr/bin/env python3
"""工作台命令行包装脚本：把项目根加入 sys.path 后转交 workbench.cli。

以隔离模式（python -I）运行时 PYTHONPATH 会被忽略，因此用本脚本显式注入路径，
数据目录始终通过命令行参数传入。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workbench.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
