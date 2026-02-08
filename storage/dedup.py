"""
Incremental deduplication and date filtering module.
Uses SQLite to track already-crawled note IDs and supports date-based filtering.

@author jinbiao.sun
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from utils.helpers import ensure_dir

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS crawled_notes (
    note_id     TEXT PRIMARY KEY,
    keyword     TEXT,
    title       TEXT,
    crawled_at  TEXT NOT NULL
);
"""


class DedupStore:
    """
    Manages a SQLite database for tracking which notes have already been crawled.
    Provides deduplication and date-range filtering capabilities.
    """

    def __init__(self, db_path: str = './data/crawled.db'):
        """
        Initialize the DedupStore.

        Args:
            db_path: Path to the SQLite database file.
        """
        ensure_dir(os.path.dirname(db_path))
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create the database and table if they don't exist."""
        conn = self._get_conn()
        conn.executescript(DB_SCHEMA)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create the SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
        return self._conn

    def is_crawled(self, note_id: str) -> bool:
        """
        Check whether a note has already been crawled.

        Args:
            note_id: The note ID to check.

        Returns:
            True if the note exists in the database.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM crawled_notes WHERE note_id = ?", (note_id,)
        )
        return cursor.fetchone() is not None

    def mark_crawled(
        self, note_id: str, keyword: str = '', title: str = ''
    ) -> None:
        """
        Record a note as crawled.

        Args:
            note_id: The note ID.
            keyword: The keyword used when crawling.
            title: The note title.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO crawled_notes (note_id, keyword, title, crawled_at)
            VALUES (?, ?, ?, ?)
            """,
            (note_id, keyword, title, datetime.now().isoformat()),
        )
        conn.commit()

    def mark_batch_crawled(
        self, notes: List[Dict[str, Any]], keyword: str = ''
    ) -> None:
        """
        Record multiple notes as crawled in one transaction.

        Args:
            notes: List of note dictionaries (must contain 'note_id').
            keyword: The keyword used when crawling.
        """
        conn = self._get_conn()
        records = [
            (
                n.get('note_id', ''),
                keyword,
                n.get('title', ''),
                datetime.now().isoformat(),
            )
            for n in notes
            if n.get('note_id')
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO crawled_notes (note_id, keyword, title, crawled_at)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        logger.info(f"Marked {len(records)} notes as crawled.")

    def filter_new(self, notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out notes that have already been crawled.

        Args:
            notes: List of note dictionaries.

        Returns:
            List of notes that are NOT yet in the database.
        """
        new_notes = []
        for note in notes:
            nid = note.get('note_id', '')
            if nid and not self.is_crawled(nid):
                new_notes.append(note)
        skipped = len(notes) - len(new_notes)
        if skipped > 0:
            logger.info(f"Skipped {skipped} already-crawled notes.")
        return new_notes

    def get_crawl_count(self) -> int:
        """Return the total number of crawled notes in the database."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM crawled_notes")
        return cursor.fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class DateFilter:
    """
    Filters notes based on their publish date.
    """

    def __init__(
        self,
        enabled: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_days: Optional[int] = None,
    ):
        """
        Initialize the DateFilter.

        Args:
            enabled: Whether date filtering is active.
            start_date: Start date string (YYYY-MM-DD), inclusive.
            end_date: End date string (YYYY-MM-DD), inclusive.
            recent_days: If set, overrides start/end to filter for the last N days.
        """
        self._enabled = enabled
        self._start: Optional[datetime] = None
        self._end: Optional[datetime] = None

        if not enabled:
            return

        if recent_days is not None:
            self._end = datetime.now()
            self._start = self._end - timedelta(days=recent_days)
        else:
            if start_date:
                self._start = datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                self._end = datetime.strptime(end_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59
                )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def passes(self, note: Dict[str, Any]) -> bool:
        """
        Check whether a note's publish time falls within the configured range.

        Args:
            note: A note dictionary with 'publish_time' (datetime or None).

        Returns:
            True if the note passes the filter (or filter is disabled).
        """
        if not self._enabled:
            return True

        pub_time = note.get('publish_time')
        if pub_time is None:
            # If we can't determine the date, include the note by default
            return True

        if self._start and pub_time < self._start:
            return False
        if self._end and pub_time > self._end:
            return False
        return True

    def filter_notes(self, notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter a list of notes by publish date.

        Args:
            notes: List of note dictionaries.

        Returns:
            Filtered list of notes within the date range.
        """
        if not self._enabled:
            return notes

        filtered = [n for n in notes if self.passes(n)]
        removed = len(notes) - len(filtered)
        if removed > 0:
            logger.info(f"Date filter removed {removed} notes outside the range.")
        return filtered
