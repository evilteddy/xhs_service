"""
Debug script: inspect the search results page's __INITIAL_STATE__
to understand how to get xsec_token for each note.

Usage:
    python debug_search_page.py "新加坡求职"
"""

import os
import sys
import json
import time
import logging

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from crawler.browser import BrowserManager
from utils.helpers import encode_keyword, build_search_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def debug_search_page(keyword: str):
    browser = BrowserManager(login_wait=0)
    try:
        page = browser.page
        encoded = encode_keyword(keyword)
        url = build_search_url(encoded, sort_by='popularity')
        logger.info(f"Navigating to search page: {url}")
        page.get(url)
        time.sleep(3)

        logger.info(f"Current URL: {page.url}")
        logger.info(f"Page title: {page.title}")

        # ===== Test 1: Top-level __INITIAL_STATE__ keys =====
        print("\n" + "=" * 70)
        print("TEST 1: __INITIAL_STATE__ top-level keys")
        print("=" * 70)
        r1 = page.run_js("""
        try {
            if (!window.__INITIAL_STATE__) return 'NOT_FOUND';
            return JSON.stringify(Object.keys(window.__INITIAL_STATE__));
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Keys: {r1}")

        # ===== Test 2: Check 'search' section =====
        print("\n" + "=" * 70)
        print("TEST 2: 'search' section structure")
        print("=" * 70)
        r2 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            if (!s || !s.search) return 'NO search section';
            var info = { searchKeys: Object.keys(s.search) };
            // Check for feeds/notes
            if (s.search.feeds) {
                info.feedsLength = s.search.feeds.length;
                if (s.search.feeds.length > 0) {
                    var first = s.search.feeds[0];
                    info.firstFeedKeys = Object.keys(first);
                    info.firstFeedId = first.id || first.note_id || first.noteId || '(none)';
                    info.firstFeedXsecToken = first.xsec_token || first.xsecToken || '(none)';
                }
            }
            if (s.search.notes) {
                info.notesLength = s.search.notes.length;
                if (s.search.notes.length > 0) {
                    info.firstNoteKeys = Object.keys(s.search.notes[0]);
                }
            }
            return JSON.stringify(info, null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Result: {r2}")

        # ===== Test 3: Check 'feed' section =====
        print("\n" + "=" * 70)
        print("TEST 3: 'feed' section structure")
        print("=" * 70)
        r3 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            if (!s || !s.feed) return 'NO feed section';
            var info = { feedKeys: Object.keys(s.feed) };
            if (s.feed.feeds) {
                info.feedsLength = s.feed.feeds.length;
                if (s.feed.feeds.length > 0) {
                    var first = s.feed.feeds[0];
                    info.firstFeedKeys = Object.keys(first);
                }
            }
            return JSON.stringify(info, null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Result: {r3}")

        # ===== Test 4: Extract first 3 notes with xsec_token from search =====
        print("\n" + "=" * 70)
        print("TEST 4: Extract notes with xsec_token from search feeds")
        print("=" * 70)
        r4 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            if (!s) return JSON.stringify({error: 'no state'});
            
            var items = [];
            
            // Try search.feeds
            var feeds = (s.search || {}).feeds || [];
            for (var i = 0; i < Math.min(feeds.length, 3); i++) {
                var f = feeds[i];
                items.push({
                    id: f.id || f.note_id || f.noteId || '(none)',
                    xsecToken: f.xsec_token || f.xsecToken || '(none)',
                    modelType: f.model_type || f.modelType || '(none)',
                    noteCardKeys: f.note_card ? Object.keys(f.note_card) : [],
                    allKeys: Object.keys(f)
                });
            }
            
            return JSON.stringify({
                feedCount: feeds.length,
                firstItems: items
            }, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r4}")

        # ===== Test 5: Check actual <a> tag hrefs =====
        print("\n" + "=" * 70)
        print("TEST 5: Check <a> tag hrefs from note cards")
        print("=" * 70)
        try:
            container = page.ele('.feeds-page', timeout=5)
            if container:
                sections = container.eles('.note-item')
                print(f"Found {len(sections)} note-item elements")
                for i, sec in enumerate(sections[:3]):
                    link_ele = sec.ele('tag:a', timeout=1)
                    if link_ele:
                        href_raw = link_ele.attr('href') or '(no href)'
                        link_resolved = link_ele.link or '(no .link)'
                        print(f"  Card {i+1}:")
                        print(f"    attr('href'): {href_raw}")
                        print(f"    .link:        {link_resolved}")
                    else:
                        print(f"  Card {i+1}: no <a> found")
            else:
                print("Cannot find .feeds-page container")
        except Exception as e:
            print(f"Error: {e}")

        # ===== Test 6: Full note card data from search state =====
        print("\n" + "=" * 70)
        print("TEST 6: Full note_card structure from first search feed item")
        print("=" * 70)
        r6 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            var feeds = (s.search || {}).feeds || (s.feed || {}).feeds || [];
            if (feeds.length === 0) return 'No feeds found';
            
            var f = feeds[0];
            var nc = f.note_card || f.noteCard || {};
            
            var result = {
                feedId: f.id || '(none)',
                xsecToken: f.xsec_token || f.xsecToken || '(none)',
                noteCardExists: !!f.note_card || !!f.noteCard,
                noteCardKeys: Object.keys(nc),
                noteCardTitle: nc.title || nc.display_title || '(none)',
                noteCardType: nc.type || '(none)',
                noteCardUser: nc.user ? { nickname: nc.user.nickname, userId: nc.user.user_id || nc.user.userId } : '(none)',
                noteCardInteract: nc.interact_info || nc.interactInfo || '(none)',
                noteCardDesc: (nc.desc || '').substring(0, 100)
            };
            return JSON.stringify(result, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r6}")

    finally:
        browser.disconnect()


if __name__ == '__main__':
    keyword = sys.argv[1] if len(sys.argv) > 1 else "新加坡求职"
    debug_search_page(keyword)
