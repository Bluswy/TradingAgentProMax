from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.tushare_provider import _require_tushare


OUTPUT_PATH = (
    ROOT
    / "tradingagents"
    / "dataflows"
    / "data_cache"
    / "ths_index_mapping.json"
)


def main() -> None:
    pro = _require_tushare()
    df = pro.ths_index(exchange="A")
    mapping: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        ts_code = str(row_dict.get("ts_code") or "").strip()
        if not ts_code:
            continue
        mapping[ts_code] = {
            "name": str(row_dict.get("name") or "").strip(),
            "type": str(row_dict.get("type") or "").strip(),
            "exchange": str(row_dict.get("exchange") or "").strip(),
            "list_date": str(row_dict.get("list_date") or "").strip(),
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(mapping)} ths index mappings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
