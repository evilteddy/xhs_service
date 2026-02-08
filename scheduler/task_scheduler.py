"""
Task scheduler module for Xiaohongshu crawler.
Uses APScheduler to support cron-based periodic crawling.

@author jinbiao.sun
"""

import logging
import signal
import sys
from typing import Callable, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Manages scheduled execution of the crawling task using APScheduler.
    Supports cron expressions for flexible scheduling.
    """

    def __init__(self):
        """Initialize the TaskScheduler with a blocking scheduler."""
        self._scheduler = BlockingScheduler()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Set up graceful shutdown signal handlers."""
        def shutdown(signum, frame):
            logger.info("Received shutdown signal, stopping scheduler...")
            self._scheduler.shutdown(wait=False)
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

    def add_cron_job(
        self,
        func: Callable,
        cron_expression: str,
        job_id: str = 'xhs_crawl',
        **kwargs,
    ) -> None:
        """
        Add a cron-scheduled job.

        Args:
            func: The function to execute on schedule.
            cron_expression: Cron expression string (e.g., '0 8 * * *').
                            Format: minute hour day month day_of_week
            job_id: Unique identifier for this job.
            **kwargs: Additional keyword arguments to pass to the function.
        """
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression '{cron_expression}'. "
                f"Expected 5 fields: minute hour day month day_of_week"
            )

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            kwargs=kwargs,
            replace_existing=True,
            misfire_grace_time=3600,  # 1 hour grace time for misfired jobs
        )
        logger.info(f"Scheduled job '{job_id}' with cron: {cron_expression}")

    def start(self) -> None:
        """
        Start the scheduler. This call blocks until the scheduler is shut down.
        """
        logger.info("Starting task scheduler (press Ctrl+C to stop)...")
        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")

    def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler shut down successfully.")


def parse_cron(cron_str: str) -> dict:
    """
    Parse a cron expression string into a dictionary.

    Args:
        cron_str: Cron expression (5 fields).

    Returns:
        Dictionary with keys: minute, hour, day, month, day_of_week.
    """
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: '{cron_str}'")
    return {
        'minute': parts[0],
        'hour': parts[1],
        'day': parts[2],
        'month': parts[3],
        'day_of_week': parts[4],
    }
