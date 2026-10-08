"""How far the recalculation runs have got, for the progress bar on the pages.

A run is what one trigger queues: the periodic task, or the recalculate button
on the settings page. It is made of jobs, one Corporation and month each, and
those run on whichever Celery workers are free - in parallel, and in any order.

Everything lives in the cache, nothing in the database: the state is only worth
something while the run lasts. Three kinds of keys keep parallel workers from
writing over each other:

- the index, the ids of the runs still worth showing - only written when a run
  starts, is dismissed or has expired, never by a job;
- one entry per run, its jobs as they were queued - written once;
- one entry per job, its state - written only by the worker running that job.

A single entry for everything, as eos-auth-monitor keeps for its one task,
would lose updates here: two workers finishing at the same moment both read
the old entry, and the later write drops the earlier job.
"""

import time
import uuid
from contextlib import contextmanager

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

PREFIX = "eos_tax:progress"
INDEX_KEY = f"{PREFIX}:runs"
LOCK_KEY = f"{PREFIX}:lock"
# long enough for a slow run - every job that moves renews it - short enough
# that a crashed worker's "running" does not stay on the page for good
TIMEOUT = 60 * 60

AUTOMATIC = "automatic"
MANUAL = "manual"

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
# update_corp ran and decided there was nothing to calculate - no tax rate, no
# entries; not an error, but not a figure either
SKIPPED = "skipped"
FAILED = "failed"

FINISHED_STATES = (DONE, SKIPPED, FAILED)


def _run_key(run_id):
    return f"{PREFIX}:run:{run_id}"


def _job_key(run_id, job_id):
    return f"{PREFIX}:job:{run_id}:{job_id}"


def job_id(corp_id, month, year):
    return f"{corp_id}:{year}-{month:02d}"


@contextmanager
def _index_lock():
    """Serialises the read-modify-write on the index.

    cache.add is atomic on every backend Django ships and on django-redis,
    which makes it a lock without depending on one backend's API. The run
    and the periodic task can start a run at the same moment; without it one
    of the two would vanish from the index. A lock that cannot be had within
    a second is skipped rather than waited for - a missing bar is better than
    a task that hangs on the cache.
    """
    acquired = False
    for _attempt in range(50):
        if cache.add(LOCK_KEY, 1, 5):
            acquired = True
            break
        time.sleep(0.02)

    if not acquired:
        logger.warning("eos_tax progress: index lock not acquired - writing without it")

    try:
        yield
    finally:
        if acquired:
            cache.delete(LOCK_KEY)


def start_run(kind, jobs):
    """Registers a run and its jobs, all queued; returns the run id.

    jobs: dicts with corp_id, corp_name, month and year.
    """
    run_id = uuid.uuid4().hex
    run = {
        "id": run_id,
        "kind": kind,
        "started_at": time.time(),
        "jobs": [
            {**job, "id": job_id(job["corp_id"], job["month"], job["year"])}
            for job in jobs
        ],
    }
    cache.set(_run_key(run_id), run, TIMEOUT)

    with _index_lock():
        index = cache.get(INDEX_KEY) or []
        cache.set(INDEX_KEY, [*index, run_id], TIMEOUT)

    return run_id


def withdraw(run_id):
    """Takes a run off the page, e.g. one whose jobs never reached the broker."""
    run = cache.get(_run_key(run_id))
    if run:
        cache.delete_many([_job_key(run_id, job["id"]) for job in run["jobs"]])
    cache.delete(_run_key(run_id))

    with _index_lock():
        index = cache.get(INDEX_KEY) or []
        cache.set(INDEX_KEY, [rid for rid in index if rid != run_id], TIMEOUT)


def set_job(run_id, job, state, detail=""):
    if not run_id:
        # a job queued before this module existed, or by hand from a shell
        return

    cache.set(
        _job_key(run_id, job),
        {"state": state, "detail": detail, "updated_at": time.time()},
        TIMEOUT,
    )
    # a run that is still moving must not expire under its own jobs
    cache.touch(_run_key(run_id), TIMEOUT)
    cache.touch(INDEX_KEY, TIMEOUT)


@contextmanager
def tracked(run_id, corp_id, month, year):
    """Marks one job running for the length of the block.

    The block hands back update_corp's result through the yielded dict's
    "result"; a result with "ok": False counts as skipped, with its reason as
    the detail. An exception marks the job failed and is raised on - the
    caller's logging and Celery's own record of the failure stay as they were.
    """
    job = job_id(corp_id, month, year)
    set_job(run_id, job, RUNNING)
    outcome = {"result": None}

    try:
        yield outcome
    except Exception as error:
        set_job(run_id, job, FAILED, f"{type(error).__name__}: {error}")
        raise

    result = outcome["result"] or {}
    if result.get("ok", True):
        set_job(run_id, job, DONE)
    else:
        set_job(run_id, job, SKIPPED, result.get("reason", ""))


def get_runs():
    """Every run still in the cache, oldest first, with the state of its jobs.

    Runs whose entry has expired are dropped from the index on the way.
    """
    index = cache.get(INDEX_KEY) or []
    if not index:
        return []

    stored = cache.get_many([_run_key(run_id) for run_id in index])
    runs = [stored[_run_key(run_id)] for run_id in index if _run_key(run_id) in stored]

    if len(runs) != len(index):
        alive = {run["id"] for run in runs}
        with _index_lock():
            current = cache.get(INDEX_KEY) or []
            # re-read under the lock: a run started since the first read stays
            cache.set(
                INDEX_KEY,
                [rid for rid in current if rid in alive or rid not in index],
                TIMEOUT,
            )

    states = cache.get_many([
        _job_key(run["id"], job["id"]) for run in runs for job in run["jobs"]
    ])

    result = []
    for run in runs:
        jobs = []
        for job in run["jobs"]:
            state = states.get(_job_key(run["id"], job["id"])) or {"state": QUEUED, "detail": ""}
            jobs.append({**job, "state": state["state"], "detail": state["detail"]})

        counts = {state: 0 for state in (QUEUED, RUNNING, DONE, SKIPPED, FAILED)}
        for job in jobs:
            counts[job["state"]] += 1

        finished = sum(counts[state] for state in FINISHED_STATES)
        total = len(jobs)
        result.append({
            "id": run["id"],
            "kind": run["kind"],
            "started_at": run["started_at"],
            "jobs": jobs,
            "counts": counts,
            "total": total,
            "finished": finished,
            "complete": finished == total,
            "percent": round(100 * finished / total) if total else 100,
        })

    return result
