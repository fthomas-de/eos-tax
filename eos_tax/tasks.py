from celery import shared_task

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from allianceauth.eveonline.models import EveCorporationInfo

from eos_tax import progress
from eos_tax.db.bot_store import store_bot_reports
from eos_tax.db.gm_transactions import store_gm_report
from eos_tax.db.payments import update_corp
from eos_tax.app_settings import get_config
from eos_tax.util import get_dates

logger = get_extension_logger(__name__)

# Create your tasks here

# One bots job per month at a time. Every visit to a tab that finds no list
# queues one, and a month takes the better part of a minute - without this a
# handful of admins opening the page would queue a handful of identical runs.
# The timeout only frees a month whose worker died before it could.
BOT_REPORT_LOCK = "eos_tax_bot_report_queued_{year}_{month}"
BOT_REPORT_LOCK_SECONDS = 15 * 60


def queue_bot_reports(dates):
    """Queues the bots page lists of each (month, year), unless already queued."""
    for month, year in dates:
        if cache.add(BOT_REPORT_LOCK.format(year=year, month=month), 1,
                     BOT_REPORT_LOCK_SECONDS):
            logger.info(f"queueing bot lists: {month}/{year}")
            run_update_bot_reports.delay(month=month, year=year)


# The same for the GM transactions page, which reads every character journal
# at once and has no month.
GM_REPORT_LOCK = "eos_tax_gm_report_queued"


def queue_gm_report():
    if cache.add(GM_REPORT_LOCK, 1, BOT_REPORT_LOCK_SECONDS):
        logger.info("queueing GM transactions")
        run_update_gm_report.delay()


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
    # the same months, so the bots page keeps pace with the tax rows
    queue_bot_reports(get_dates())
    queue_gm_report()

# helper task
@shared_task
def run_update_corporation(corp_id:int, month: int = -1, year: int = -1, run_id: str = None):
    # run_id defaults to None so a subtask queued by the previous version,
    # still waiting in the broker during an upgrade, runs without a bar
    with progress.tracked(run_id, corp_id, month, year) as outcome:
        outcome["result"] = update_corp(corp_id=corp_id, month=month, year=year)


@shared_task
def run_update_bot_reports(month: int, year: int):
    try:
        store_bot_reports(year, month)
    finally:
        # also after a failure, so the next visit can queue it again
        cache.delete(BOT_REPORT_LOCK.format(year=year, month=month))


@shared_task
def run_update_gm_report():
    try:
        store_gm_report()
    finally:
        cache.delete(GM_REPORT_LOCK)
