"""Worker that claims leased VSAM migration jobs, in this process or a separate one.

``python -m enterprise.vsam.worker --database <url> --data-root <dir>`` runs a worker against the same database and data
directory as the API (start the API with ``inline_workers=False`` so it only queues). Several workers may run at once;
each job is leased to exactly one at a time, a dead worker's job is picked up again after its lease expires and resumes
from its checkpoint, and a job that keeps failing ends as ``FAILED`` with ``RETRIES_EXHAUSTED``.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import uuid
from pathlib import Path

from enterprise.vsam.jobs import VsamJobService

_LOG = logging.getLogger(__name__)


class VsamWorker:
    def __init__(self, service: VsamJobService, worker_id: str | None = None, lease_seconds: int | None = None,
                 poll_seconds: float = 1.0) -> None:
        self._service = service
        self.worker_id = worker_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._lease_seconds = lease_seconds
        self._poll_seconds = poll_seconds

    def run_once(self) -> bool:
        """Claim and run one job; ``False`` when nothing was runnable."""
        job_id = self._service.claim_next(self.worker_id, self._lease_seconds)
        if job_id is None:
            return False
        _LOG.info("worker %s claimed job %s", self.worker_id, job_id)
        self._service.process(job_id, self.worker_id, self._lease_seconds)
        return True

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                busy = self.run_once()
            except Exception:  # noqa: BLE001 - keep the worker alive; the job's lease will expire and be retried
                _LOG.exception("worker %s iteration failed", self.worker_id)
                busy = False
            if not busy:
                stop.wait(self._poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="SQLite path or postgresql:// URL (never logged)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    service = VsamJobService(args.database, args.data_root, inline_workers=False)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    VsamWorker(service, poll_seconds=args.poll_seconds).run_forever(stop)
    service.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
