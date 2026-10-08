from celery import shared_task

from allianceauth.services.hooks import get_extension_logger
from allianceauth.eveonline.models import EveCorporationInfo

from eos_tax import progress
from eos_tax.db.payments import update_corp
from eos_tax.app_settings import get_config
from eos_tax.util import get_dates

logger = get_extension_logger(__name__)

# Create your tasks here

def queue_corporations(corporations, dates, kind):
    """Queues one subtask per Corporation and month, as one run of the
    progress bar. corporations: (corp_id, corp_name) pairs.

    The run is registered before the first subtask is queued: a worker that
    picks one up at once must find its run already there.
    """
    jobs = [
        {"corp_id": corp_id, "corp_name": corp_name, "month": month, "year": year}
        for corp_id, corp_name in corporations
        for month, year in dates
    ]
    if not jobs:
        return None

    run_id = progress.start_run(kind, jobs)

    try:
        for job in jobs:
            logger.info(f"queueing: {job['corp_name']} ({job['corp_id']}), date: {job['month']}/{job['year']}")
            # split for parallel processing
            run_update_corporation.delay(
                corp_id=job["corp_id"], month=job["month"], year=job["year"], run_id=run_id
            )
    except Exception:
        # the broker is down: the jobs not queued would stand at "queued" for
        # an hour, a bar that never moves
        progress.withdraw(run_id)
        raise

    return run_id


# main task
@shared_task
def run_update_alliance():
    # one query for the whole list. Walking every corporation and resolving its
    # alliance one by one cost a query per corporation, which is the bulk of the
    # work once an alliance has its corporations registered in Alliance Auth.
    corporations = EveCorporationInfo.objects.filter(
        alliance__alliance_id__in=get_config().alliance_ids()
    ).values_list("corporation_id", "corporation_name")

    queue_corporations(corporations, get_dates(), progress.AUTOMATIC)

# helper task
@shared_task
def run_update_corporation(corp_id:int, month: int = -1, year: int = -1, run_id: str = None):
    # run_id defaults to None so a subtask queued by the previous version,
    # still waiting in the broker during an upgrade, runs without a bar
    with progress.tracked(run_id, corp_id, month, year) as outcome:
        outcome["result"] = update_corp(corp_id=corp_id, month=month, year=year)
