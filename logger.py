"""Append-only local log, for a doctor's own record of AI drafts used."""
import json
import time

import config


def log_event(**fields) -> None:
    if config.PUBLIC_MODE:
        return                      # a shared server keeps no activity log
    config.LOG_DIR.mkdir(exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **fields}
    with open(config.EVENTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
