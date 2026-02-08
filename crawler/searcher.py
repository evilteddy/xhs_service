"""
Search and pagination module for Xiaohongshu crawler.
Handles keyword search, page scrolling, and note link collection.

@author jinbiao.sun
"""

import json
import time
import random
import logging
from typing import List, Dict, Any

from crawler.browser import BrowserManager
from utils.helpers import encode_keyword, build_search_url

logger = logging.getLogger(__name__)

# Base URL used to resolve relative hrefs from the search page
_XHS_BASE = "https://www.xiaohongshu.com"


class Searcher:
    """
    Performs keyword searches on Xiaohongshu and collects note card data
    from the search results page by scrolling through pages.
    """

    def __init__(
        self,
        browser: BrowserManager,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
    ):
        """
        Initialize the Searcher.

        Args:
            browser: BrowserManager instance.
            min_delay: Minimum delay in seconds between scroll actions.
            max_delay: Maximum delay in seconds between scroll actions.
        """
        self._browser = browser
        self._min_delay = min_delay
        self._max_delay = max_delay

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, keyword: str, sort_by: str = 'general') -> None:
        """
        Navigate to the Xiaohongshu search results page for the given keyword.
        Automatically dismisses the login modal that XHS may show and waits
        until note cards are visible.

        Args:
            keyword: The raw search keyword.
            sort_by: Sort order for results ('general', 'popularity', 'time').
        """
        encoded = encode_keyword(keyword)
        url = build_search_url(encoded, sort_by=sort_by)
        sort_label = {
            'general': '综合', 'popularity': '最热', 'time': '最新',
        }.get(sort_by, sort_by)
        logger.info(f"Searching for keyword: '{keyword}' (sort: {sort_label})")
        self._browser.navigate(url)
        # Wait for initial page structure to render
        time.sleep(3)

        # XHS often pops up a login modal that blocks search results.
        # Try to dismiss it repeatedly for up to 10 seconds.
        self._wait_for_search_results()

    def collect_note_cards(
        self, scroll_times: int = 20, max_notes: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Scroll through the search results and collect basic note card info.

        Each card contains:
          - note_link: Full URL with xsec_token (required to open the note)
          - title: Note title (from search card)
          - author: Author nickname
          - author_link: URL to author profile
          - likes: Like count text
          - note_id: Extracted from the note_link

        Args:
            scroll_times: Number of times to scroll down.
            max_notes: Maximum number of note cards to collect.

        Returns:
            List of note card dictionaries.
        """
        page = self._browser.page
        collected: Dict[str, Dict[str, Any]] = {}  # keyed by note_id for dedup

        for i in range(1, scroll_times + 1):
            logger.info(
                f"Scroll iteration {i}/{scroll_times}, "
                f"collected so far: {len(collected)}"
            )

            cards = self._extract_cards_from_page(page)
            for card in cards:
                nid = card.get('note_id')
                if nid and nid not in collected:
                    collected[nid] = card

            if len(collected) >= max_notes:
                logger.info(
                    f"Reached max_notes limit ({max_notes}), stopping scroll."
                )
                break

            self._scroll_down(page)

        results = list(collected.values())[:max_notes]
        logger.info(f"Collected {len(results)} unique note cards.")
        return results

    # ------------------------------------------------------------------
    # Login-modal handling & page-load waiting
    # ------------------------------------------------------------------

    def _wait_for_search_results(self, timeout: int = 15) -> None:
        """
        Wait until note-item cards are visible on the search results page.
        Repeatedly dismisses the login modal (which XHS shows before
        rendering the cards) and checks for note items.

        Args:
            timeout: Maximum seconds to wait.
        """
        page = self._browser.page
        start = time.time()
        while time.time() - start < timeout:
            # Try to dismiss login modal
            self._dismiss_login_modal()
            # Check if note items have appeared
            count = page.run_js(
                "return document.querySelectorAll('.note-item').length;"
            )
            if count and int(count) > 0:
                logger.info(f"Search results loaded: {count} note cards visible.")
                return
            time.sleep(1)
        logger.warning(
            f"Timed out waiting for search results after {timeout}s. "
            f"Proceeding anyway."
        )

    def _dismiss_login_modal(self) -> None:
        """
        Dismiss the login modal that XHS sometimes pops up on the
        search results page.  Without dismissing it the note cards
        behind it never finish loading.
        """
        page = self._browser.page
        try:
            dismissed = page.run_js("""
            try {
                var modal = document.querySelector('.login-modal');
                if (!modal) return 'no_modal';
                var closeBtn = modal.querySelector('.close-button')
                            || modal.querySelector('.icon-btn-wrapper');
                if (closeBtn) { closeBtn.click(); return 'closed'; }
                var mask = modal.querySelector('.reds-mask');
                if (mask) { mask.click(); return 'mask_clicked'; }
                modal.style.display = 'none';
                return 'hidden';
            } catch(e) { return 'error:' + e.message; }
            """)
            if dismissed and dismissed != 'no_modal':
                logger.info(f"Login modal dismissed ({dismissed}).")
        except Exception as e:
            logger.debug(f"Error trying to dismiss login modal: {e}")

    # ------------------------------------------------------------------
    # Card extraction
    # ------------------------------------------------------------------

    # JavaScript snippet that extracts all note card data from the search
    # results page.  Runs entirely in the browser so we avoid any
    # DrissionPage attribute-access quirks.  Returns a JSON array of cards.
    #
    # Key insight: XHS search-result cards have TWO kinds of <a>:
    #   1. <a href="/explore/{id}">  — plain wrapper, NO xsec_token
    #   2. <a class="cover ..." href="/search_result/{id}?xsec_token=...">
    #      — cover link, HAS xsec_token (note: path is /search_result/, not /explore/)
    # We need the cover link and must rewrite /search_result/ → /explore/.
    _JS_EXTRACT_CARDS = """
    var cards = [];
    var items = document.querySelectorAll('.note-item');
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var noteLink = '';
        var noteId = '';

        // Gather ALL <a> in this card
        var allLinks = item.querySelectorAll('a');

        // Strategy 1: find <a> with xsec_token in href
        for (var j = 0; j < allLinks.length; j++) {
            var href = allLinks[j].getAttribute('href') || '';
            if (href.indexOf('xsec_token') !== -1 &&
                (href.indexOf('/explore/') !== -1 || href.indexOf('/search_result/') !== -1)) {
                noteLink = href;
                break;
            }
        }

        // Strategy 2: find <a class="cover ...">
        if (!noteLink) {
            for (var j = 0; j < allLinks.length; j++) {
                var cls = allLinks[j].className || '';
                if (cls.indexOf('cover') !== -1) {
                    noteLink = allLinks[j].getAttribute('href') || '';
                    break;
                }
            }
        }

        // Strategy 3: first <a> with /explore/
        if (!noteLink) {
            for (var j = 0; j < allLinks.length; j++) {
                var href2 = allLinks[j].getAttribute('href') || '';
                if (href2.indexOf('/explore/') !== -1) {
                    noteLink = href2;
                    break;
                }
            }
        }

        if (!noteLink) continue;

        // Rewrite /search_result/ → /explore/ so the URL opens a full note page
        noteLink = noteLink.replace('/search_result/', '/explore/');

        // Extract note_id from the URL path
        var pathPart = noteLink.split('?')[0].replace(/\\/+$/, '');
        var pathParts = pathPart.split('/');
        noteId = pathParts[pathParts.length - 1] || '';
        if (!noteId) continue;

        // Make the link absolute
        if (noteLink.charAt(0) === '/') {
            noteLink = 'https://www.xiaohongshu.com' + noteLink;
        }

        // Footer data
        var title = '';
        var author = '';
        var authorLink = '';
        var likes = '';

        var footer = item.querySelector('.footer');
        if (footer) {
            var titleEl = footer.querySelector('.title');
            if (titleEl) title = (titleEl.textContent || '').trim();

            var authorWrapper = footer.querySelector('.author-wrapper');
            if (authorWrapper) {
                var authorEl = authorWrapper.querySelector('.author');
                if (authorEl) author = (authorEl.textContent || '').trim();
                var authorLinkEl = authorWrapper.querySelector('a');
                if (authorLinkEl) {
                    authorLink = authorLinkEl.getAttribute('href') || '';
                    if (authorLink.charAt(0) === '/') {
                        authorLink = 'https://www.xiaohongshu.com' + authorLink;
                    }
                }
            }

            var likeEl = footer.querySelector('.like-wrapper');
            if (likeEl) {
                var likeSpan = likeEl.querySelector('span');
                likes = (likeSpan ? likeSpan.textContent : likeEl.textContent) || '';
                likes = likes.trim();
            }
        }

        cards.push({
            note_id: noteId,
            note_link: noteLink,
            title: title,
            author: author,
            author_link: authorLink,
            likes: likes
        });
    }
    return JSON.stringify(cards);
    """

    def _extract_cards_from_page(self, page) -> List[Dict[str, Any]]:
        """
        Extract note card information from the currently loaded search page
        using JavaScript for maximum reliability.

        Args:
            page: The DrissionPage tab/page instance.

        Returns:
            List of card dictionaries.
        """
        cards: List[Dict[str, Any]] = []
        try:
            raw = page.run_js(self._JS_EXTRACT_CARDS)
            if not raw:
                logger.warning("JS card extraction returned nothing.")
                return cards

            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                cards = parsed
                logger.debug(
                    f"JS extracted {len(cards)} cards, "
                    f"sample link: {cards[0]['note_link'][:80] if cards else 'N/A'}"
                )
            else:
                logger.warning(f"JS card extraction returned unexpected type: {type(parsed)}")

        except Exception as e:
            logger.warning(f"Error extracting cards via JS: {e}")
            # Fallback to DOM-based extraction
            cards = self._extract_cards_from_dom(page)

        return cards

    def _extract_cards_from_dom(self, page) -> List[Dict[str, Any]]:
        """
        Fallback: extract note cards via DrissionPage DOM selectors.

        Args:
            page: The DrissionPage tab/page instance.

        Returns:
            List of card dictionaries.
        """
        cards = []
        try:
            container = page.ele('.feeds-page', timeout=5)
            if not container:
                return cards
            sections = container.eles('.note-item')
            for section in sections:
                try:
                    card = self._parse_card_dom(section)
                    if card:
                        cards.append(card)
                except Exception as e:
                    logger.debug(f"Failed to parse a note card via DOM: {e}")
        except Exception as e:
            logger.warning(f"Error in DOM card extraction: {e}")
        return cards

    def _parse_card_dom(self, section) -> Dict[str, Any] | None:
        """
        Parse a single note-item section using DrissionPage elements.
        This is the fallback when JS extraction fails.

        Args:
            section: A DrissionPage element representing one note card.

        Returns:
            Dictionary with card data, or None if parsing fails.
        """
        link_ele = section.ele('tag:a', timeout=0)
        if not link_ele:
            return None
        href = link_ele.attr('href') or link_ele.link or ''
        note_link = self._resolve_url(href)
        note_id = self._extract_note_id(href)
        if not note_link or not note_id:
            return None

        footer = section.ele('.footer', timeout=0)
        title = ''
        author = ''
        author_link = ''
        likes = ''
        if footer:
            title_ele = footer.ele('.title', timeout=0)
            if title_ele:
                title = title_ele.text or ''
            author_wrapper = footer.ele('.author-wrapper', timeout=0)
            if author_wrapper:
                author_ele = author_wrapper.ele('.author', timeout=0)
                if author_ele:
                    author = author_ele.text or ''
                author_link_ele = author_wrapper.ele('tag:a', timeout=0)
                if author_link_ele:
                    author_link = author_link_ele.link or ''
            like_ele = footer.ele('.like-wrapper', timeout=0)
            if like_ele:
                like_count_ele = like_ele.ele('tag:span', timeout=0)
                likes = (
                    like_count_ele.text if like_count_ele else like_ele.text
                ) or ''

        return {
            'note_id': note_id,
            'note_link': note_link,
            'title': title,
            'author': author,
            'author_link': author_link,
            'likes': likes,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_url(href: str) -> str:
        """
        Turn a relative XHS href into an absolute URL.

        Args:
            href: Raw href string (may be relative like ``/explore/...``).

        Returns:
            Absolute URL string.
        """
        if not href:
            return ''
        href = href.strip()
        if href.startswith('http'):
            return href
        if href.startswith('/'):
            return _XHS_BASE + href
        return href

    @staticmethod
    def _extract_note_id(url: str) -> str:
        """
        Extract the note ID from a Xiaohongshu note URL.
        Example: ``/explore/65a1b2c3...?xsec_token=...`` → ``65a1b2c3...``

        Args:
            url: The note URL (absolute or relative).

        Returns:
            The note ID string, or empty string if extraction fails.
        """
        if not url:
            return ''
        # Strip query parameters for ID extraction
        path = url.split('?')[0].rstrip('/')
        parts = path.split('/')
        if parts:
            return parts[-1]
        return ''

    def _scroll_down(self, page) -> None:
        """
        Scroll the page down with a random delay to simulate human behavior.

        Args:
            page: The DrissionPage tab/page instance.
        """
        delay = random.uniform(self._min_delay, self._max_delay)
        time.sleep(delay)
        page.scroll.to_bottom()
