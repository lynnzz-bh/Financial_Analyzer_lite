"""本模块负责把原始数据、清洗数据和中间结果写入本地文件。它屏蔽 DataFrame、字典和列表的保存差异，便于主流程按阶段留痕。"""

from pathlib import Path
import json

import pandas as pd


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(data: object, path: Path) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def save_dataframe(df: pd.DataFrame, path: Path) -> Path:
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
