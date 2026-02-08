"""
Note detail extractor module for Xiaohongshu crawler.
Visits individual note pages and extracts full note information
by reading the __INITIAL_STATE__ JS variable that contains structured data.
Falls back to DOM selectors when JS data is unavailable.

@author jinbiao.sun
"""

import json
import re
import time
import random
import logging
from typing import Dict, Any, List
from datetime import datetime

from crawler.browser import BrowserManager
from utils.helpers import parse_count, parse_publish_time

logger = logging.getLogger(__name__)

# JavaScript snippet to extract ONLY the fields we need from __INITIAL_STATE__.
# This avoids JSON.stringify on the full state (which often fails due to
# circular references, undefined values, or proxied objects).
_JS_EXTRACT = """
try {
    var state = window.__INITIAL_STATE__;
    if (!state || !state.note) return null;

    var noteMap = state.note.noteDetailMap || state.note.noteDetail || {};
    var keys = Object.keys(noteMap);
    if (keys.length === 0) return null;

    // Pick the first (usually only) entry in the map
    var entry = noteMap[keys[0]];
    var n = entry.note || entry;
    if (!n) return null;

    var user = n.user || {};
    var interact = n.interactInfo || {};
    var images = (n.imageList || []).map(function(img) {
        return {
            urlDefault: img.urlDefault || '',
            urlPre: img.urlPre || '',
            url: img.url || '',
            infoList: (img.infoList || []).map(function(info) {
                return { url: info.url || '' };
            })
        };
    });
    var tags = (n.tagList || []).map(function(tag) {
        return { name: tag.name || '', id: tag.id || '' };
    });

    // Build a clean, serializable object
    var result = {
        noteId: n.noteId || '',
        type: n.type || '',
        title: n.title || '',
        desc: n.desc || '',
        user: {
            nickname: user.nickname || '',
            userId: user.userId || user.uid || ''
        },
        interactInfo: {
            likedCount: String(interact.likedCount || '0'),
            commentCount: String(interact.commentCount || '0'),
            collectedCount: String(interact.collectedCount || '0'),
            shareCount: String(interact.shareCount || '0')
        },
        time: n.time ? String(n.time) : '',
        ipLocation: n.ipLocation || '',
        imageList: images,
        tagList: tags
    };
    return JSON.stringify(result);
} catch(e) {
    return null;
}
"""


class NoteExtractor:
    """
    Extracts detailed information from individual Xiaohongshu note pages.
    Primary strategy: parse window.__INITIAL_STATE__ for structured data.
    Fallback strategy: use DOM CSS selectors.

    Optionally performs random "like" actions on note detail pages based on
    a configurable probability and per-run cap.

    @author jinbiao.sun
    """

    def __init__(
        self,
        browser: BrowserManager,
        detail_page_delay: float = 1.0,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        like_config: Dict[str, Any] | None = None,
    ):
        """
        Initialize the NoteExtractor.

        Args:
            browser: BrowserManager instance.
            detail_page_delay: Base delay before extracting detail page.
            min_delay: Minimum random delay addition.
            max_delay: Maximum random delay addition.
            like_config: Configuration dict for random liking behaviour.
                Keys: enabled (bool), probability (float 0-1),
                max_likes_per_run (int), delay_after_like (float seconds).
        """
        self._browser = browser
        self._detail_page_delay = detail_page_delay
        self._min_delay = min_delay
        self._max_delay = max_delay

        # Like feature configuration
        like_cfg = like_config or {}
        self._like_enabled: bool = like_cfg.get('enabled', False)
        self._like_probability: float = like_cfg.get('probability', 0.1)
        self._like_max: int = like_cfg.get('max_likes_per_run', 5)
        self._like_delay: float = like_cfg.get('delay_after_like', 2.0)
        self._like_count: int = 0  # tracks how many likes performed this run

    def extract_note_detail(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """
        Visit a note's detail page and extract full information.

        Args:
            card: Basic card data from the searcher, must include 'note_link'.

        Returns:
            Enriched dictionary with full note details.
        """
        note_link = card.get('note_link', '')
        note_id = card.get('note_id', '')
        logger.info(f"Extracting detail for note: {note_id}")

        result = {
            'note_id': note_id,
            'note_link': note_link,
            'note_type': '',       # 'normal'=图文, 'video'=视频
            'title': card.get('title', ''),
            'content': '',
            'author': card.get('author', ''),
            'author_id': '',
            'author_link': card.get('author_link', ''),
            'likes': 0,
            'comments': 0,
            'collects': 0,
            'shares': 0,
            'publish_time': None,
            'publish_time_str': '',
            'image_urls': [],
            'tags': [],
            'liked': False,        # whether we liked this note during crawl
        }

        if not note_link:
            logger.warning(f"No link for note {note_id}, skipping detail extraction.")
            return result

        try:
            self._browser.navigate(note_link)
            # Random delay to mimic human reading and wait for page load
            delay = self._detail_page_delay + random.uniform(self._min_delay, self._max_delay)
            time.sleep(delay)

            page = self._browser.page

            # Dismiss any login modal that may appear on the note page
            self._dismiss_login_modal(page)

            # Strategy 1: Extract from __INITIAL_STATE__ JS variable (most reliable)
            # Try up to 2 times — the first attempt can fail with "页面被刷新"
            # if the page hasn't finished its SPA transition yet.
            js_data = None
            for attempt in range(2):
                js_data = self._extract_from_initial_state(page, note_id)
                if js_data:
                    break
                if attempt == 0:
                    logger.debug(
                        f"__INITIAL_STATE__ attempt 1 failed for {note_id}, "
                        f"waiting 2s and retrying..."
                    )
                    time.sleep(2)

            if js_data:
                result = self._merge_js_data(result, js_data)
                logger.debug(f"Extracted note {note_id} via __INITIAL_STATE__")
            else:
                # Strategy 2: Fall back to DOM selectors
                logger.info(f"__INITIAL_STATE__ extraction failed for {note_id}, trying DOM selectors")
                result = self._extract_from_dom(page, result)

        except Exception as e:
            error_msg = str(e).lower()
            logger.error(f"Failed to extract detail for note {note_id}: {e}")

            # Detect browser disconnection and attempt to reconnect
            if 'disconnected' in error_msg or 'connection' in error_msg:
                logger.warning(
                    "Browser connection lost. Attempting to reconnect..."
                )
                try:
                    self._browser.reconnect()
                    logger.info("Reconnected. Will retry remaining notes.")
                except Exception as re_err:
                    logger.error(f"Reconnection failed: {re_err}")

        # Keep the original note_link from the search card (it has xsec_token).
        # Only set a fallback if there's no link at all.
        if not result.get('note_link') and result.get('note_id'):
            result['note_link'] = f"https://www.xiaohongshu.com/explore/{result['note_id']}"

        # Randomly like this note if the feature is enabled
        if self._should_like():
            page = self._browser.page
            if self._perform_like(page, note_id):
                result['liked'] = True

        return result

    def extract_notes_batch(
        self,
        cards: List[Dict[str, Any]],
        progress_callback=None,
        max_consecutive_failures: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Extract details for a batch of note cards.

        Tracks consecutive extraction failures and aborts early if the
        browser appears to be unresponsive (e.g. after a connection drop
        that could not be recovered).

        Args:
            cards: List of card dictionaries from the searcher.
            progress_callback: Optional callable(current, total) for progress reporting.
            max_consecutive_failures: Stop the batch after this many
                consecutive notes fail to extract any meaningful data.

        Returns:
            List of enriched note detail dictionaries.
        """
        results = []
        total = len(cards)
        consecutive_failures = 0

        for idx, card in enumerate(cards, 1):
            if progress_callback:
                progress_callback(idx, total)

            detail = self.extract_note_detail(card)
            results.append(detail)

            # A note is considered "failed" if it has no title, no content,
            # and zero likes — meaning extraction yielded nothing useful.
            if (
                not detail.get('title')
                and not detail.get('content')
                and detail.get('likes', 0) == 0
            ):
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(
                        f"Aborting batch extraction: {consecutive_failures} "
                        f"consecutive failures detected — browser may be "
                        f"unresponsive. Successfully extracted "
                        f"{idx - consecutive_failures}/{total} notes."
                    )
                    break
            else:
                consecutive_failures = 0

        return results

    # -----------------------------------------------------------------------
    # Login modal helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _dismiss_login_modal(page) -> None:
        """Dismiss the XHS login modal if it appears on the note page."""
        try:
            page.run_js("""
            try {
                var m = document.querySelector('.login-modal');
                if (!m) return;
                var b = m.querySelector('.close-button')
                      || m.querySelector('.icon-btn-wrapper');
                if (b) { b.click(); return; }
                var mask = m.querySelector('.reds-mask');
                if (mask) { mask.click(); return; }
                m.style.display = 'none';
            } catch(e) {}
            """)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Random like feature
    # -----------------------------------------------------------------------

    def _should_like(self) -> bool:
        """
        Decide whether to like the current note based on probability and
        the remaining like quota for this run.

        Returns:
            True if a like action should be performed, False otherwise.
        """
        if not self._like_enabled:
            return False
        if self._like_count >= self._like_max:
            return False
        return random.random() < self._like_probability

    def _perform_like(self, page, note_id: str) -> bool:
        """
        Attempt to click the like button on the current note detail page.

        Uses multiple CSS selector strategies to locate the like button,
        then clicks it via JavaScript.  A random delay is added afterwards
        to simulate human behaviour.

        Args:
            page: The DrissionPage tab/page instance.
            note_id: The note ID (used for logging).

        Returns:
            True if the like was performed successfully, False otherwise.
        """
        try:
            # JavaScript to find and click the like button on the detail page.
            # The XHS detail page has a like-wrapper element in the engage bar.
            # We check if the note is already liked (active/liked state) to
            # avoid toggling an existing like off.
            liked = page.run_js("""
            try {
                // Strategy 1: .like-wrapper in the engage/interact bar
                var likeBtn = document.querySelector('.like-wrapper')
                           || document.querySelector('.engage-bar .like')
                           || document.querySelector('[class*="like-wrapper"]');
                if (!likeBtn) return 'no_button';

                // Check if already liked — XHS adds 'active' or 'liked' class
                var cls = likeBtn.className || '';
                if (cls.indexOf('active') !== -1 || cls.indexOf('liked') !== -1) {
                    return 'already_liked';
                }

                // Also check via a child SVG or icon that may carry the state
                var icon = likeBtn.querySelector('svg')
                        || likeBtn.querySelector('[class*="like-icon"]')
                        || likeBtn.querySelector('.like-icon');
                if (icon) {
                    var iconCls = icon.className || '';
                    if (typeof iconCls === 'object' && iconCls.baseVal) {
                        iconCls = iconCls.baseVal;
                    }
                    if (iconCls.indexOf('active') !== -1 ||
                        iconCls.indexOf('liked') !== -1) {
                        return 'already_liked';
                    }
                }

                likeBtn.click();
                return 'liked';
            } catch(e) {
                return 'error:' + e.message;
            }
            """)

            if liked == 'liked':
                self._like_count += 1
                logger.info(
                    f"Liked note {note_id} "
                    f"({self._like_count}/{self._like_max} likes used)."
                )
                # Random delay after liking to mimic human behaviour
                delay = self._like_delay + random.uniform(0.5, 1.5)
                time.sleep(delay)
                return True
            elif liked == 'already_liked':
                logger.debug(f"Note {note_id} is already liked, skipping.")
            elif liked == 'no_button':
                logger.debug(f"Like button not found for note {note_id}.")
            else:
                logger.debug(f"Like action result for note {note_id}: {liked}")

        except Exception as e:
            logger.warning(f"Error performing like on note {note_id}: {e}")

        return False

    # -----------------------------------------------------------------------
    # Strategy 1: Extract from window.__INITIAL_STATE__
    # -----------------------------------------------------------------------

    def _extract_from_initial_state(self, page, note_id: str) -> Dict[str, Any] | None:
        """
        Extract note data from the window.__INITIAL_STATE__ JavaScript variable.
        Only serializes the fields we actually need (avoids full-object
        serialization failures).

        Note: DrissionPage may return the result of ``JSON.stringify()`` either
        as a Python ``str`` **or** as an already-parsed ``dict``, depending on
        the browser driver version.  We handle both cases.

        Args:
            page: The DrissionPage tab/page instance.
            note_id: The note ID to look up.

        Returns:
            Parsed note data dict, or None if extraction fails.
        """
        try:
            raw = page.run_js(_JS_EXTRACT)
            if not raw:
                logger.debug("__INITIAL_STATE__ extraction returned nothing.")
                return None

            # DrissionPage might auto-parse JSON → dict, or return a raw string
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, dict):
                data = raw
            else:
                logger.debug(f"__INITIAL_STATE__ returned unexpected type: {type(raw)}")
                return None

            return self._build_from_note_obj(data, note_id)

        except json.JSONDecodeError as e:
            logger.debug(f"JSON decode error from __INITIAL_STATE__: {e}")
            return None
        except Exception as e:
            logger.debug(f"Error extracting __INITIAL_STATE__: {e}")
            return None

    def _build_from_note_obj(self, note: dict, original_note_id: str = '') -> Dict[str, Any]:
        """
        Build a result dict from the cleaned note data extracted by JavaScript.

        Args:
            note: The cleaned note object from __INITIAL_STATE__.
            original_note_id: The note ID from the searcher (fallback).

        Returns:
            Structured result dict.
        """
        result = {}

        # Note ID & type
        result['note_id'] = note.get('noteId', '') or original_note_id
        result['note_type'] = note.get('type', '')  # 'normal' or 'video'

        # Title
        result['title'] = note.get('title', '')

        # Content / description
        result['content'] = note.get('desc', '')

        # Author
        user = note.get('user', {})
        result['author'] = user.get('nickname', '')
        result['author_id'] = user.get('userId', '')
        result['author_link'] = (
            f"https://www.xiaohongshu.com/user/profile/{result['author_id']}"
            if result['author_id'] else ''
        )

        # Interaction counts
        interact = note.get('interactInfo', {})
        result['likes'] = self._safe_int(interact.get('likedCount', '0'))
        result['comments'] = self._safe_int(interact.get('commentCount', '0'))
        result['collects'] = self._safe_int(interact.get('collectedCount', '0'))
        result['shares'] = self._safe_int(interact.get('shareCount', '0'))

        # Publish time (XHS stores millisecond timestamps)
        timestamp = note.get('time', '')
        result['publish_time'] = None
        result['publish_time_str'] = ''
        if timestamp:
            try:
                ts = int(timestamp)
                if ts > 1e12:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts)
                result['publish_time'] = dt
                result['publish_time_str'] = dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError, OSError):
                result['publish_time_str'] = str(timestamp)

        ip_location = note.get('ipLocation', '')
        if ip_location and result['publish_time_str']:
            result['publish_time_str'] += f' ({ip_location})'

        # Images — filter out avatars
        image_list = note.get('imageList', [])
        result['image_urls'] = []
        for img in image_list:
            url = (
                img.get('urlDefault', '')
                or img.get('urlPre', '')
                or img.get('url', '')
            )
            # Try infoList as last resort
            if not url:
                info_list = img.get('infoList', [])
                if info_list:
                    url = info_list[0].get('url', '')

            if url:
                if url.startswith('//'):
                    url = 'https:' + url
                elif not url.startswith('http'):
                    url = 'https://' + url
                # Skip avatar images
                if '/avatar/' not in url:
                    result['image_urls'].append(url)

        # Tags
        tag_list = note.get('tagList', [])
        result['tags'] = [t.get('name', '') for t in tag_list if t.get('name')]

        # Also extract hashtags from desc text
        if result['content']:
            hashtags = re.findall(r'#(\S+?)#', result['content'])
            for ht in hashtags:
                if ht not in result['tags']:
                    result['tags'].append(ht)

        return result

    # -----------------------------------------------------------------------
    # Strategy 2: Fallback DOM selector extraction
    # -----------------------------------------------------------------------

    def _extract_from_dom(self, page, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract note details using DOM CSS selectors as a fallback.

        Args:
            page: The DrissionPage tab/page instance.
            result: The result dict to enrich.

        Returns:
            The enriched result dict.
        """
        # Title
        result['title'] = self._dom_get_text(page, [
            '#detail-title',
            'css:.note-detail .title',
            'css:[class*="title"]',
        ]) or result['title']

        # Content / description
        content = self._dom_get_text(page, [
            '#detail-desc',
            'css:.note-detail .desc',
            'css:.note-scroller .desc',
            'css:[class*="desc"]',
            'css:.note-text',
        ])
        if content:
            result['content'] = content

        # Author info
        author_name = self._dom_get_text(page, [
            'css:.note-detail .username',
            'css:.author-container .username',
            'css:[class*="username"]',
            'css:.author',
        ])
        if author_name:
            result['author'] = author_name

        # Author link
        author_link_ele = self._dom_find_element(page, [
            'css:.note-detail .author-wrapper a',
            'css:.author-container a',
            'css:[class*="username"] tag:a',
        ])
        if author_link_ele:
            link = getattr(author_link_ele, 'link', '') or ''
            if link:
                result['author_link'] = link
                parts = link.rstrip('/').split('/')
                if parts:
                    result['author_id'] = parts[-1].split('?')[0]

        # Interaction counts
        result['likes'] = self._dom_get_count(page, [
            'css:.like-wrapper .count',
            'css:.like-wrapper span:last-child',
            'css:[class*="like"] .count',
            'css:[class*="like"] span',
        ])
        result['comments'] = self._dom_get_count(page, [
            'css:.chat-wrapper .count',
            'css:.chat-wrapper span:last-child',
            'css:[class*="chat"] .count',
            'css:[class*="comment"] .count',
        ])
        result['collects'] = self._dom_get_count(page, [
            'css:.collect-wrapper .count',
            'css:.collect-wrapper span:last-child',
            'css:[class*="collect"] .count',
            'css:[class*="star"] .count',
        ])

        # Publish time
        time_str = self._dom_get_text(page, [
            'css:.note-detail .date',
            'css:.bottom-container .date',
            'css:.note-scroller .date',
            'css:[class*="date"]',
        ])
        if time_str:
            result['publish_time_str'] = time_str
            result['publish_time'] = parse_publish_time(time_str)

        # Images
        result['image_urls'] = self._dom_get_images(page)

        # Tags
        result['tags'] = self._dom_get_tags(page)

        # Assume image-text note for DOM extraction (no video info available)
        result['note_type'] = 'normal'

        return result

    def _dom_get_text(self, page, selectors: List[str]) -> str:
        """Try multiple selectors to extract text content."""
        for sel in selectors:
            try:
                ele = page.ele(sel, timeout=2)
                if ele:
                    text = ele.text
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ''

    def _dom_find_element(self, page, selectors: List[str]):
        """Try multiple selectors to find an element."""
        for sel in selectors:
            try:
                ele = page.ele(sel, timeout=1)
                if ele:
                    return ele
            except Exception:
                continue
        return None

    def _dom_get_count(self, page, selectors: List[str]) -> int:
        """Try multiple selectors to extract a numeric count."""
        for sel in selectors:
            try:
                ele = page.ele(sel, timeout=1)
                if ele:
                    text = ele.text
                    if text and text.strip():
                        return parse_count(text)
            except Exception:
                continue
        return 0

    def _dom_get_images(self, page) -> List[str]:
        """Extract note images from DOM, filtering out avatars."""
        urls = []
        try:
            container_selectors = [
                'css:.swiper-wrapper',
                'css:.carousel-container',
                'css:.note-slider-img',
                'css:.note-detail .note-image',
                'css:.note-content',
                'css:div[class*="slider"]',
                'css:div[class*="carousel"]',
                'css:div[class*="swiper"]',
            ]
            container = None
            for sel in container_selectors:
                try:
                    container = page.ele(sel, timeout=2)
                    if container:
                        break
                except Exception:
                    continue

            images = container.eles('tag:img') if container else page.eles('tag:img')

            for img in images:
                src = img.attr('src') or img.attr('data-src') or ''
                if not src:
                    continue
                if 'xhscdn' not in src:
                    continue
                if '/avatar/' in src or 'emoji' in src or 'icon' in src:
                    continue
                clean_url = src.split('?')[0] if '?' in src else src
                if clean_url and clean_url not in urls:
                    urls.append(clean_url)
        except Exception as e:
            logger.debug(f"Error extracting images from DOM: {e}")
        return urls

    def _dom_get_tags(self, page) -> List[str]:
        """Extract hashtags / tags from DOM."""
        tags = []
        try:
            tag_selectors = [
                'css:#detail-desc a[class*="tag"]',
                'css:.note-detail a[class*="tag"]',
                'css:a[class*="hash"]',
                'css:.tag',
            ]
            for sel in tag_selectors:
                try:
                    tag_elements = page.eles(sel, timeout=1)
                    if tag_elements:
                        for t in tag_elements:
                            if t.text:
                                tag_text = t.text.strip().lstrip('#').rstrip('#')
                                if tag_text and tag_text not in tags:
                                    tags.append(tag_text)
                        if tags:
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Error extracting tags from DOM: {e}")
        return tags

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _merge_js_data(self, result: Dict[str, Any], js_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge JS-extracted data into the result dict, preferring JS data
        for non-empty values.
        """
        for key, value in js_data.items():
            # For strings, only override if non-empty
            if isinstance(value, str):
                if value:
                    result[key] = value
            # For lists, only override if non-empty
            elif isinstance(value, list):
                if value:
                    result[key] = value
            # For numbers, always override (0 is valid)
            elif isinstance(value, (int, float)):
                result[key] = value
            # For other types (datetime, etc.), override if truthy
            elif value is not None:
                result[key] = value
        return result

    @staticmethod
    def _safe_int(value) -> int:
        """Safely convert a value to int."""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return parse_count(value)
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
