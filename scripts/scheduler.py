import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from crawl.crawl_analyst_reports import main as run_analyst_crawl
from crawl.crawl_financial_reports import main as run_bctc_crawl
from crawl.crawl_news import main as run_news_crawl
from scripts.analyze_sentiment import process_pending_news
from scripts.extract_financial_metrics import process_pending as run_metrics_extraction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("scheduler")


async def crawl_news_job():
    log.info("crawl_news START")
    try:
        await run_news_crawl()
    except Exception as e:
        log.exception("crawl_news failed: %s", e)
    log.info("crawl_news DONE")


async def crawl_analyst_job():
    log.info("crawl_analyst START")
    try:
        await run_analyst_crawl()
    except Exception as e:
        log.exception("crawl_analyst failed: %s", e)
    log.info("crawl_analyst DONE")


async def crawl_bctc_job():
    log.info("crawl_bctc START")
    try:
        await run_bctc_crawl()
    except Exception as e:
        log.exception("crawl_bctc failed: %s", e)
    log.info("crawl_bctc DONE")


async def analyze_sentiment_job():
    """Process any unanalyzed news rows. Idempotent — safe to run frequently."""
    log.info("analyze_sentiment START")
    try:
        # process_pending_news is sync — offload to a worker thread
        await asyncio.to_thread(process_pending_news)
    except Exception as e:
        log.exception("analyze_sentiment failed: %s", e)
    log.info("analyze_sentiment DONE")


async def extract_metrics_job():
    """Extract financial metrics from any BCTC rows not yet processed. Idempotent."""
    log.info("extract_metrics START")
    try:
        await asyncio.to_thread(run_metrics_extraction)
    except Exception as e:
        log.exception("extract_metrics failed: %s", e)
    log.info("extract_metrics DONE")


async def main():
    scheduler = AsyncIOScheduler()

    # Crawlers
    scheduler.add_job(
        crawl_news_job,
        IntervalTrigger(minutes=30),
        id="crawl_news",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )

    scheduler.add_job(
        crawl_analyst_job,
        CronTrigger(hour=8, minute=0),
        id="crawl_analyst",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        crawl_bctc_job,
        CronTrigger(hour=6, minute=0),
        id="crawl_bctc",
        max_instances=1,
        coalesce=True,
    )

    # Processors — independent of crawls. They poll for pending rows and process them.
    scheduler.add_job(
        analyze_sentiment_job,
        IntervalTrigger(minutes=15),
        id="analyze_sentiment",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        extract_metrics_job,
        IntervalTrigger(hours=1),
        id="extract_metrics",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    log.info(
        "Scheduler started. Jobs registered: %s", [j.id for j in scheduler.get_jobs()]
    )
    log.info("Press Ctrl+C to exit.")

    try:
        await asyncio.Event().wait()  # block forever
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down scheduler")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
