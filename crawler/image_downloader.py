"""
Image downloader module for Xiaohongshu crawler.
Downloads note images with retry support and organizes them by note ID.

@author jinbiao.sun
"""

import os
import logging
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from utils.helpers import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)

# Default request headers to mimic a browser
DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://www.xiaohongshu.com/',
}


class ImageDownloader:
    """
    Downloads images from Xiaohongshu note pages.
    Supports concurrent downloads, retry on failure, and organized storage.
    """

    def __init__(
        self,
        image_dir: str = './data/images',
        max_workers: int = 3,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        """
        Initialize the ImageDownloader.

        Args:
            image_dir: Base directory for storing downloaded images.
            max_workers: Number of concurrent download threads.
            max_retries: Maximum number of retry attempts per image.
            timeout: HTTP request timeout in seconds.
        """
        self._image_dir = image_dir
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._timeout = timeout
        ensure_dir(image_dir)

    def download_note_images(self, note: Dict[str, Any]) -> List[str]:
        """
        Download all images for a single note.

        Args:
            note: Note dictionary containing 'note_id' and 'image_urls'.

        Returns:
            List of local file paths of downloaded images.
        """
        note_id = note.get('note_id', 'unknown')
        image_urls = note.get('image_urls', [])

        if not image_urls:
            logger.debug(f"No images to download for note {note_id}")
            return []

        # Create a sub-directory for this note
        note_dir = ensure_dir(os.path.join(self._image_dir, sanitize_filename(note_id)))
        downloaded = []

        for idx, url in enumerate(image_urls, 1):
            filename = f"{note_id}_{idx}.jpg"
            filepath = os.path.join(note_dir, filename)

            # Skip if already downloaded
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.debug(f"Image already exists: {filepath}")
                downloaded.append(filepath)
                continue

            result = self._download_single(url, filepath)
            if result:
                downloaded.append(result)

        logger.info(
            f"Downloaded {len(downloaded)}/{len(image_urls)} images for note {note_id}"
        )
        return downloaded

    def download_batch(self, notes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """
        Download images for a batch of notes using a thread pool.

        Args:
            notes: List of note dictionaries.

        Returns:
            Dictionary mapping note_id -> list of downloaded file paths.
        """
        results: Dict[str, List[str]] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_note = {
                executor.submit(self.download_note_images, note): note
                for note in notes
                if note.get('image_urls')
            }

            for future in as_completed(future_to_note):
                note = future_to_note[future]
                note_id = note.get('note_id', 'unknown')
                try:
                    paths = future.result()
                    results[note_id] = paths
                except Exception as e:
                    logger.error(f"Error downloading images for note {note_id}: {e}")
                    results[note_id] = []

        return results

    def _download_single(self, url: str, filepath: str) -> str | None:
        """
        Download a single image with retry logic.

        Args:
            url: Image URL.
            filepath: Local file path to save to.

        Returns:
            File path if successful, None otherwise.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=self._timeout,
                    stream=True,
                )
                response.raise_for_status()

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                logger.debug(f"Downloaded: {filepath}")
                return filepath

            except requests.RequestException as e:
                logger.warning(
                    f"Download attempt {attempt}/{self._max_retries} failed for {url}: {e}"
                )
                if attempt < self._max_retries:
                    time.sleep(1 * attempt)  # exponential-ish backoff

        logger.error(f"Failed to download image after {self._max_retries} attempts: {url}")
        # Clean up partial file
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        return None
