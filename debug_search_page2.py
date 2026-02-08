"""
Debug script 2: deeper investigation of search page structure.
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


def debug_search_page2(keyword: str):
    browser = BrowserManager(login_wait=0)
    try:
        page = browser.page
        encoded = encode_keyword(keyword)
        url = build_search_url(encoded, sort_by='popularity')
        logger.info(f"Navigating to: {url}")
        page.get(url)
        time.sleep(5)  # Wait longer

        # ===== Test 1: Check search.feeds more carefully =====
        print("\n" + "=" * 70)
        print("TEST 1: search.feeds deep inspection")
        print("=" * 70)
        r1 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            var feeds = s.search.feeds;
            var info = {
                type: typeof feeds,
                isArray: Array.isArray(feeds),
                length: feeds ? feeds.length : -1,
                hasSymbol: feeds ? (typeof feeds[Symbol.iterator] === 'function') : false
            };
            
            // Try to iterate manually
            if (feeds && feeds.length > 0) {
                var firstKeys = [];
                try {
                    var f = feeds[0];
                    firstKeys = Object.keys(f);
                    info.firstItemKeys = firstKeys;
                    info.firstItemId = f.id || '(none)';
                    info.firstItemXsec = f.xsec_token || '(none)';
                } catch(e2) {
                    info.iterError = e2.message;
                }
            }
            
            // Try spreading/converting
            try {
                var arr = Array.from(feeds);
                info.arrayFromLength = arr.length;
                if (arr.length > 0) {
                    info.arrayFirstKeys = Object.keys(arr[0]);
                    info.arrayFirstId = arr[0].id || '(none)';
                    info.arrayFirstXsec = arr[0].xsec_token || '(none)';
                }
            } catch(e3) {
                info.arrayFromError = e3.message;
            }
            
            // Try JSON.parse(JSON.stringify()) to unwrap Proxy
            try {
                var raw = JSON.parse(JSON.stringify(feeds));
                info.jsonRoundtripLength = raw.length;
                if (raw.length > 0) {
                    info.jsonFirstKeys = Object.keys(raw[0]);
                    info.jsonFirstId = raw[0].id || '(none)';
                    info.jsonFirstXsec = raw[0].xsec_token || '(none)';
                }
            } catch(e4) {
                info.jsonRoundtripError = e4.message;
            }
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r1}")

        # ===== Test 2: Check searchFeedsWrapper =====
        print("\n" + "=" * 70)
        print("TEST 2: search.searchFeedsWrapper")
        print("=" * 70)
        r2 = page.run_js("""
        try {
            var w = window.__INITIAL_STATE__.search.searchFeedsWrapper;
            if (!w) return 'null/undefined';
            var info = {
                type: typeof w,
                keys: Object.keys(w)
            };
            // Check each key
            for (var k of Object.keys(w)) {
                var v = w[k];
                info[k + '_type'] = typeof v;
                if (Array.isArray(v)) {
                    info[k + '_len'] = v.length;
                    if (v.length > 0) {
                        try {
                            info[k + '_firstKeys'] = Object.keys(v[0]);
                        } catch(e) {}
                    }
                }
            }
            return JSON.stringify(info, null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Result: {r2}")

        # ===== Test 3: DOM inspection — find actual card elements =====
        print("\n" + "=" * 70)
        print("TEST 3: DOM structure investigation")
        print("=" * 70)
        r3 = page.run_js("""
        try {
            var info = {};
            // Check common container selectors
            var selectors = [
                '.feeds-page',
                '.feeds-container',
                '.search-feeds',
                '#feeds-page',
                '[class*="feed"]',
                '.note-item',
                'section.note-item',
                '[class*="note-item"]',
                '[class*="noteItem"]',
                'a[href*="/explore/"]',
                'a[href*="/discovery/"]',
                '.search-result-container',
                '#search-result',
                '[id*="search"]',
                '[class*="search"]',
                '[class*="waterfall"]',
                '[class*="masonry"]',
            ];
            for (var sel of selectors) {
                var els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    info[sel] = els.length;
                }
            }
            return JSON.stringify(info, null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Found elements: {r3}")

        # ===== Test 4: Find all <a> tags with /explore/ in href =====
        print("\n" + "=" * 70)
        print("TEST 4: All <a> tags with /explore/ in href")
        print("=" * 70)
        r4 = page.run_js("""
        try {
            var links = document.querySelectorAll('a[href*="/explore/"]');
            var results = [];
            for (var i = 0; i < Math.min(links.length, 5); i++) {
                results.push({
                    href: links[i].getAttribute('href'),
                    textPreview: (links[i].textContent || '').substring(0, 50).trim(),
                    className: links[i].className,
                    parentClass: links[i].parentElement ? links[i].parentElement.className : ''
                });
            }
            return JSON.stringify({count: links.length, samples: results}, null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Result: {r4}")

        # ===== Test 5: Page body class/id for structural understanding =====
        print("\n" + "=" * 70)
        print("TEST 5: Main content structure")
        print("=" * 70)
        r5 = page.run_js("""
        try {
            // Get the first few levels of the DOM
            var mainContent = document.getElementById('content-area') || 
                             document.getElementById('app') || 
                             document.querySelector('main') ||
                             document.body;
            
            function getStructure(el, depth) {
                if (depth > 3 || !el) return null;
                var children = [];
                for (var i = 0; i < Math.min(el.children.length, 10); i++) {
                    var child = el.children[i];
                    var tag = child.tagName.toLowerCase();
                    var cls = child.className ? ('.' + String(child.className).split(' ').slice(0, 3).join('.')) : '';
                    var id = child.id ? ('#' + child.id) : '';
                    children.push({
                        selector: tag + id + cls,
                        childCount: child.children.length,
                        children: getStructure(child, depth + 1)
                    });
                }
                return children;
            }
            
            return JSON.stringify(getStructure(mainContent, 0), null, 2);
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        # Only print first 3000 chars
        print(f"Result (first 3000 chars): {str(r5)[:3000]}")

        # ===== Test 6: Scroll down and check again =====
        print("\n" + "=" * 70)
        print("TEST 6: After scrolling, check feeds and DOM")
        print("=" * 70)
        page.scroll.to_bottom()
        time.sleep(2)
        
        r6 = page.run_js("""
        try {
            var feeds = window.__INITIAL_STATE__.search.feeds;
            var links = document.querySelectorAll('a[href*="/explore/"]');
            var info = {
                feedsLength: feeds ? feeds.length : -1,
                exploreLinksCount: links.length,
            };
            
            // Try JSON roundtrip on feeds
            try {
                var raw = JSON.parse(JSON.stringify(feeds));
                info.jsonFeedsLength = raw.length;
                if (raw.length > 0) {
                    info.firstFeed = {
                        id: raw[0].id,
                        xsec_token: raw[0].xsec_token,
                        model_type: raw[0].model_type,
                        note_card_title: (raw[0].note_card || {}).display_title || '(none)'
                    };
                }
            } catch(e) {
                info.jsonError = e.message;
            }
            
            // Sample explore links
            if (links.length > 0) {
                info.sampleLinks = [];
                for (var i = 0; i < Math.min(links.length, 3); i++) {
                    info.sampleLinks.push(links[i].getAttribute('href'));
                }
            }
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r6}")

    finally:
        browser.disconnect()


if __name__ == '__main__':
    keyword = sys.argv[1] if len(sys.argv) > 1 else "新加坡求职"
    debug_search_page2(keyword)
