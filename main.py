"""
Main entry point for the Xiaohongshu (Little Red Book) crawler.

Usage:
    # First run — login via QR code (browser stays open after login)
    python main.py --login

    # Single crawl (reuses the already-open browser, no re-login needed)
    python main.py --keyword "Python" --max-notes 50

    # Use a config file
    python main.py --config config.yaml

    # Start the scheduled crawler
    python main.py --schedule

    # Explicitly close the browser when done
    python main.py --close-browser

@author jinbiao.sun
"""

import os
import sys
import argparse
import logging

import yaml
from tqdm import tqdm

# Ensure the project root is on sys.path so relative imports work
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from crawler.browser import BrowserManager
from crawler.searcher import Searcher
from crawler.extractor import NoteExtractor
from crawler.image_downloader import ImageDownloader
from storage.dedup import DedupStore, DateFilter
from storage.exporter import DataExporter
from scheduler.task_scheduler import TaskScheduler
from utils.helpers import setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    'search': {
        'keywords': ['Python'],
        'max_notes': 100,
        'scroll_times': 20,
        'sort_by': 'popularity',  # 'general', 'popularity', 'time'
    },
    'filter': {
        'date_range': {
            'enabled': True,
            'start_date': None,
            'end_date': None,
            'recent_days': 180,       # Default: last 6 months
        },
        'min_likes': 10,
        'note_type': 'normal',        # 'normal'=图文, 'video'=视频, ''=all
    },
    'output': {
        'formats': ['excel', 'csv', 'json'],
        'download_images': True,
        'output_dir': './data/exports',
        'image_dir': './data/images',
    },
    'scheduler': {
        'enabled': False,
        'cron': '0 8 * * *',
    },
    'behavior': {
        'min_delay': 0.5,
        'max_delay': 2.0,
        'detail_page_delay': 1.0,
        'login_wait': 20,
        'like': {
            'enabled': False,
            'probability': 0.1,
            'max_likes_per_run': 5,
            'delay_after_like': 2.0,
        },
    },
    'google_sheets': {
        'credentials_file': '',
        'spreadsheet_id': '',
        'spreadsheet_name': '小红书爬虫数据',
        'share_with': '',
    },
}


def load_config(config_path: str | None = None) -> dict:
    """
    Load configuration from a YAML file, merged with defaults.

    Args:
        config_path: Path to a YAML config file, or None for defaults.

    Returns:
        Merged configuration dictionary.
    """
    config = DEFAULT_CONFIG.copy()
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_cfg = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_cfg)
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Core crawl workflow
# ---------------------------------------------------------------------------

def run_crawl(config: dict, do_login: bool = False) -> None:
    """
    Execute the full crawl workflow for all configured keywords.

    Args:
        config: The merged configuration dictionary.
        do_login: If True, perform QR-code login before crawling.
    """
    behavior = config['behavior']
    search_cfg = config['search']
    filter_cfg = config['filter']
    output_cfg = config['output']

    # Initialize components
    browser = BrowserManager(login_wait=behavior.get('login_wait', 20))

    if do_login:
        browser.login()
        browser.disconnect()  # Keep browser open with the logged-in session
        return  # After login, user can re-run without --login

    searcher = Searcher(
        browser=browser,
        min_delay=behavior.get('min_delay', 0.5),
        max_delay=behavior.get('max_delay', 2.0),
    )
    like_cfg = behavior.get('like', {})
    extractor = NoteExtractor(
        browser=browser,
        detail_page_delay=behavior.get('detail_page_delay', 1.0),
        min_delay=behavior.get('min_delay', 0.5),
        max_delay=behavior.get('max_delay', 2.0),
        like_config=like_cfg,
    )

    dedup = DedupStore(db_path=os.path.join(PROJECT_ROOT, 'data', 'crawled.db'))
    date_filter = DateFilter(
        enabled=filter_cfg.get('date_range', {}).get('enabled', False),
        start_date=filter_cfg.get('date_range', {}).get('start_date'),
        end_date=filter_cfg.get('date_range', {}).get('end_date'),
        recent_days=filter_cfg.get('date_range', {}).get('recent_days'),
    )

    gsheet_cfg = config.get('google_sheets', {})
    exporter = DataExporter(
        output_dir=output_cfg.get('output_dir', './data/exports'),
        google_sheets_config=gsheet_cfg,
    )

    image_downloader = None
    if output_cfg.get('download_images', True):
        image_downloader = ImageDownloader(
            image_dir=output_cfg.get('image_dir', './data/images')
        )

    keywords = search_cfg.get('keywords', [])
    max_notes = search_cfg.get('max_notes', 100)
    scroll_times = search_cfg.get('scroll_times', 20)
    sort_by = search_cfg.get('sort_by', 'popularity')
    min_likes = filter_cfg.get('min_likes', 0)
    note_type_filter = filter_cfg.get('note_type', '')  # 'normal', 'video', or ''

    try:
        for keyword in keywords:
            logger.info(f"{'='*60}")
            logger.info(f"Starting crawl for keyword: '{keyword}'")
            logger.info(f"{'='*60}")

            _crawl_keyword(
                keyword=keyword,
                searcher=searcher,
                extractor=extractor,
                dedup=dedup,
                date_filter=date_filter,
                exporter=exporter,
                image_downloader=image_downloader,
                max_notes=max_notes,
                scroll_times=scroll_times,
                sort_by=sort_by,
                min_likes=min_likes,
                note_type_filter=note_type_filter,
                output_formats=output_cfg.get('formats', ['excel', 'csv', 'json']),
            )
    finally:
        dedup.close()
        # Only disconnect — the browser stays open so login session persists.
        # Use `python main.py --close-browser` to explicitly close it.
        browser.disconnect()

    logger.info("All crawling tasks completed!")


def _crawl_keyword(
    keyword: str,
    searcher: Searcher,
    extractor: NoteExtractor,
    dedup: DedupStore,
    date_filter: DateFilter,
    exporter: DataExporter,
    image_downloader: ImageDownloader | None,
    max_notes: int,
    scroll_times: int,
    sort_by: str,
    min_likes: int,
    note_type_filter: str,
    output_formats: list,
) -> None:
    """
    Crawl a single keyword end-to-end.

    Args:
        keyword: The search keyword.
        searcher: Searcher instance.
        extractor: NoteExtractor instance.
        dedup: DedupStore instance.
        date_filter: DateFilter instance.
        exporter: DataExporter instance.
        image_downloader: ImageDownloader or None.
        max_notes: Max number of notes to collect.
        scroll_times: Number of scroll-down actions.
        sort_by: Sort order for search results.
        min_likes: Minimum likes filter threshold.
        note_type_filter: Note type filter ('normal'=图文, 'video'=视频, ''=all).
        output_formats: List of output format strings.
    """
    # Step 1: Search and collect note cards (sorted by popularity if configured)
    searcher.search(keyword, sort_by=sort_by)
    cards = searcher.collect_note_cards(
        scroll_times=scroll_times,
        max_notes=max_notes,
    )
    if not cards:
        logger.warning(f"No notes found for keyword: '{keyword}'")
        return

    # Step 2: Incremental dedup — skip already-crawled notes
    new_cards = dedup.filter_new(cards)
    if not new_cards:
        logger.info(f"All notes for '{keyword}' have been crawled previously.")
        return

    logger.info(f"Extracting details for {len(new_cards)} new notes...")

    # Step 3: Extract full details from each note's page
    notes = []
    with tqdm(total=len(new_cards), desc="Extracting notes") as pbar:
        def progress(current, total):
            pbar.update(1)

        notes = extractor.extract_notes_batch(new_cards, progress_callback=progress)

    # Step 4: Filter by note type (图文/视频)
    if note_type_filter:
        type_label = {'normal': '图文', 'video': '视频'}.get(note_type_filter, note_type_filter)
        before = len(notes)
        notes = [n for n in notes if n.get('note_type', '') == note_type_filter]
        removed = before - len(notes)
        if removed > 0:
            logger.info(f"Note type filter ('{type_label}') removed {removed} non-matching notes.")

    # Step 5: Apply date filter
    notes = date_filter.filter_notes(notes)

    # Step 6: Apply minimum likes filter
    if min_likes > 0:
        before = len(notes)
        notes = [n for n in notes if n.get('likes', 0) >= min_likes]
        removed = before - len(notes)
        if removed > 0:
            logger.info(f"Likes filter removed {removed} notes below {min_likes} likes.")

    if not notes:
        logger.warning(f"No notes remaining after filtering for keyword: '{keyword}'")
        return

    # Step 7: Sort by comments descending — most discussed notes first
    notes.sort(key=lambda n: n.get('comments', 0), reverse=True)

    logger.info(f"Collected {len(notes)} notes after all filters (sorted by comments ↓).")

    # Step 6: Download images if enabled
    if image_downloader:
        logger.info("Downloading images...")
        image_downloader.download_batch(notes)

    # Step 7: Export data
    created_files = exporter.export(notes, keyword=keyword, formats=output_formats)
    for f in created_files:
        logger.info(f"Exported: {f}")

    # Step 8: Mark notes as crawled for incremental dedup
    dedup.mark_batch_crawled(notes, keyword=keyword)

    logger.info(f"Finished crawling keyword: '{keyword}'")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Xiaohongshu (Little Red Book) note crawler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=None,
        help='Path to YAML config file (default: config.yaml in project root)',
    )
    parser.add_argument(
        '--keyword', '-k',
        type=str,
        default=None,
        help='Search keyword (overrides config file)',
    )
    parser.add_argument(
        '--max-notes', '-n',
        type=int,
        default=None,
        help='Maximum notes to crawl per keyword (overrides config)',
    )
    parser.add_argument(
        '--scroll-times', '-s',
        type=int,
        default=None,
        help='Number of page scroll-downs (overrides config)',
    )
    parser.add_argument(
        '--login',
        action='store_true',
        help='Open browser for QR code login (first-time setup)',
    )
    parser.add_argument(
        '--schedule',
        action='store_true',
        help='Run the crawler as a scheduled task',
    )
    parser.add_argument(
        '--sort',
        type=str,
        choices=['general', 'popularity', 'time'],
        default=None,
        help="Sort order for search results: 'general'(综合), 'popularity'(最热), 'time'(最新). Default: popularity",
    )
    parser.add_argument(
        '--min-likes',
        type=int,
        default=None,
        help='Minimum likes threshold to keep a note (overrides config)',
    )
    parser.add_argument(
        '--close-browser',
        action='store_true',
        help='Close the browser and exit (frees the browser process)',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose/debug logging',
    )
    return parser


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)

    # Determine config file
    config_path = args.config
    if config_path is None:
        default_cfg = os.path.join(PROJECT_ROOT, 'config.yaml')
        if os.path.exists(default_cfg):
            config_path = default_cfg

    config = load_config(config_path)

    # Apply CLI overrides
    if args.keyword:
        config['search']['keywords'] = [args.keyword]
    if args.max_notes is not None:
        config['search']['max_notes'] = args.max_notes
    if args.scroll_times is not None:
        config['search']['scroll_times'] = args.scroll_times
    if args.sort is not None:
        config['search']['sort_by'] = args.sort
    if args.min_likes is not None:
        config['filter']['min_likes'] = args.min_likes

    # Close-browser mode
    if args.close_browser:
        logger.info("Closing browser...")
        browser = BrowserManager(login_wait=0)
        browser.close()
        logger.info("Browser closed.")
        return

    # Login mode
    if args.login:
        logger.info("Login mode: opening browser for QR code login...")
        run_crawl(config, do_login=True)
        return

    # Schedule mode
    if args.schedule:
        cron_expr = config.get('scheduler', {}).get('cron', '0 8 * * *')
        logger.info(f"Starting scheduled crawler with cron: {cron_expr}")
        scheduler = TaskScheduler()
        scheduler.add_cron_job(
            func=run_crawl,
            cron_expression=cron_expr,
            config=config,
            do_login=False,
        )
        scheduler.start()
        return

    # Normal single-run mode
    run_crawl(config, do_login=False)


if __name__ == '__main__':
    main()
