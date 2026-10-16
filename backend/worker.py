"""Varredura de alertas fora do processo da API (cron, Kubernetes CronJob...).

    python -m backend.worker            # uma varredura e sai
    python -m backend.worker --loop     # roda continuamente
"""
from __future__ import annotations

import argparse
import logging
import time

from .config import Settings
from .db import DB
from .notifications import PushSender, scan_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    db = DB(settings.database_url)
    push = PushSender(settings)
    while True:
        with db.Session() as s, s.begin():
            n = scan_all(s, push)
        logging.info("Varredura concluída: %d notificações", n)
        if not args.loop:
            break
        time.sleep(settings.scheduler_interval_s)


if __name__ == "__main__":
    main()
