"""查看交接资料的列和记录数。"""
import argparse
import csv
import json
from pathlib import Path


def describe(directory):
    tables = []
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            header, *records = csv.reader(handle, strict=True)
        if not header or len(header) != len(set(header)):
            raise ValueError(f"{path.name} 的列名缺失或重复")
        if any(len(record) != len(header) for record in records):
            raise ValueError(f"{path.name} 有一行与表头宽度不一致")
        tables.append({"文件": path.name, "列": header, "记录数": len(records)})
    return tables


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="核对本地交接资料")
    parser.add_argument("directory", type=Path, help="资料目录")
    args = parser.parse_args()
    print(json.dumps(describe(args.directory), ensure_ascii=False, indent=2))
