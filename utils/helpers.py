"""
Utility helper functions for the Xiaohongshu crawler.

@author jinbiao.sun
"""

import os
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)


def encode_keyword(keyword: str) -> str:
    """
    Encode a keyword for use in Xiaohongshu search URL.

    Args:
        keyword: The search keyword string.

    Returns:
        URL-encoded keyword string.
    """
    keyword_temp_code = quote(keyword.encode('utf-8'))
    keyword_encode = quote(keyword_temp_code.encode('gb2312'))
    return keyword_encode


def build_search_url(keyword_encoded: str, sort_by: str = 'general') -> str:
    """
    Build the full search URL for Xiaohongshu.

    Args:
        keyword_encoded: URL-encoded keyword.
        sort_by: Sort order for search results. Options:
            - 'general': Default/comprehensive ranking (综合).
            - 'popularity': Sort by popularity/most liked (最热).
            - 'time': Sort by latest publish time (最新).

    Returns:
        Full search URL string.
    """
    # Map user-friendly sort names to Xiaohongshu URL parameter values
    sort_map = {
        'general': 'general',
        'popularity': 'popularity_descending',
        'time': 'time_descending',
    }
    sort_value = sort_map.get(sort_by, 'general')
    return (
        f"https://www.xiaohongshu.com/search_result"
        f"?keyword={keyword_encoded}&source=web_search_result_notes"
        f"&sort={sort_value}"
    )


def parse_count(text: str) -> int:
    """
    Parse a count string like '1.2万' or '1234' into an integer.

    Args:
        text: The count text from the page.

    Returns:
        Parsed integer count.
    """
    if not text or text.strip() == '':
        return 0
    text = text.strip()
    try:
        if '万' in text:
            return int(float(text.replace('万', '')) * 10000)
        elif '亿' in text:
            return int(float(text.replace('亿', '')) * 100000000)
        else:
            return int(text)
    except (ValueError, TypeError):
        return 0


def parse_publish_time(time_str: str) -> datetime | None:
    """
    Parse Xiaohongshu publish time strings into datetime objects.
    Handles formats like:
      - '2024-01-15'
      - '01-15'  (current year assumed)
      - '3天前'
      - '5小时前'
      - '刚刚'
      - '昨天 14:30'
      - 'x分钟前'

    Args:
        time_str: The publish time string from the page.

    Returns:
        Parsed datetime object, or None if parsing fails.
    """
    if not time_str:
        return None
    time_str = time_str.strip()
    now = datetime.now()

    try:
        # Full date: 2024-01-15
        if re.match(r'^\d{4}-\d{2}-\d{2}', time_str):
            return datetime.strptime(time_str[:10], '%Y-%m-%d')

        # Month-day only: 01-15 (possibly followed by location text like ' 新加坡')
        match = re.match(r'^(\d{2}-\d{2})', time_str)
        if match:
            return datetime.strptime(f'{now.year}-{match.group(1)}', '%Y-%m-%d')

        # N days ago
        match = re.match(r'(\d+)\s*天前', time_str)
        if match:
            days = int(match.group(1))
            return now - timedelta(days=days)

        # N hours ago
        match = re.match(r'(\d+)\s*小时前', time_str)
        if match:
            hours = int(match.group(1))
            return now - timedelta(hours=hours)

        # N minutes ago
        match = re.match(r'(\d+)\s*分钟前', time_str)
        if match:
            minutes = int(match.group(1))
            return now - timedelta(minutes=minutes)

        # Just now
        if '刚刚' in time_str:
            return now

        # Yesterday
        if '昨天' in time_str:
            return now - timedelta(days=1)

    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse time string '{time_str}': {e}")
        return None

    logger.warning(f"Unrecognized time format: '{time_str}'")
    return None


def ensure_dir(path: str) -> str:
    """
    Ensure a directory exists, create it if not.

    Args:
        path: Directory path.

    Returns:
        The same directory path.
    """
    os.makedirs(path, exist_ok=True)
    return path


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    Sanitize a string for use as a filename.

    Args:
        name: The raw filename string.
        max_length: Maximum length of the output filename.

    Returns:
        Sanitized filename string.
    """
    # Remove characters that are invalid in filenames
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    # Remove leading/trailing whitespace and dots
    name = name.strip().strip('.')
    # Truncate if too long
    if len(name) > max_length:
        name = name[:max_length]
    return name or 'unnamed'


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure logging for the application.

    Args:
        level: Logging level (default INFO).
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
