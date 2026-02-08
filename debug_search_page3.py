"""
Debug script 3: dismiss login modal, wait for results,
inspect Vue Proxy feeds and actual <a> hrefs.
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


def debug_search_page3(keyword: str):
    browser = BrowserManager(login_wait=0)
    try:
        page = browser.page
        encoded = encode_keyword(keyword)
        url = build_search_url(encoded, sort_by='popularity')
        logger.info(f"Navigating to: {url}")
        page.get(url)
        time.sleep(3)

        # ===== Step 0: Dismiss login modal if present =====
        print("\n" + "=" * 70)
        print("STEP 0: Dismiss login modal")
        print("=" * 70)
        r0 = page.run_js("""
        try {
            var modal = document.querySelector('.login-modal');
            if (modal) {
                // Try closing it
                var closeBtn = modal.querySelector('.close-button') || 
                               modal.querySelector('.icon-btn-wrapper');
                if (closeBtn) {
                    closeBtn.click();
                    return 'Clicked close button';
                }
                // Try clicking the mask to dismiss
                var mask = modal.querySelector('.reds-mask');
                if (mask) {
                    mask.click();
                    return 'Clicked mask to dismiss';
                }
                // Last resort: hide it
                modal.style.display = 'none';
                return 'Hid modal via style';
            }
            return 'No login modal found';
        } catch(e) { return 'ERROR: ' + e.message; }
        """)
        print(f"Result: {r0}")
        time.sleep(3)  # Wait for content to load after dismissing

        # ===== Step 1: Check if search results are now visible =====
        print("\n" + "=" * 70)
        print("STEP 1: Check search results visibility after dismissing modal")
        print("=" * 70)
        r1 = page.run_js("""
        try {
            var info = {};
            // Check for explore links
            var exploreLinks = document.querySelectorAll('a[href*="/explore/"]');
            info.exploreLinksCount = exploreLinks.length;
            
            // Check for any links with xsec_token
            var allLinks = document.querySelectorAll('a');
            var xsecLinks = [];
            for (var i = 0; i < allLinks.length; i++) {
                var href = allLinks[i].getAttribute('href') || '';
                if (href.includes('xsec_token')) {
                    xsecLinks.push(href.substring(0, 120));
                }
            }
            info.xsecLinksCount = xsecLinks.length;
            info.xsecLinksSample = xsecLinks.slice(0, 3);
            
            // Note item elements
            var noteItems = document.querySelectorAll('.note-item');
            info.noteItemCount = noteItems.length;
            
            // Check various selectors
            var sections = document.querySelectorAll('section');
            info.sectionCount = sections.length;
            
            // Check for any cover/card elements
            var covers = document.querySelectorAll('[class*="cover"]');
            info.coverCount = covers.length;
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r1}")

        # ===== Step 2: Use _rawValue to bypass Vue Proxy =====
        print("\n" + "=" * 70)
        print("STEP 2: Access search.feeds via _rawValue (bypass Vue Proxy)")
        print("=" * 70)
        r2 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            // Try multiple paths to access the raw feeds data
            var feeds = null;
            
            // Path 1: searchFeedsWrapper._rawValue
            if (s.search && s.search.searchFeedsWrapper && s.search.searchFeedsWrapper._rawValue) {
                feeds = s.search.searchFeedsWrapper._rawValue;
            }
            
            // Path 2: searchFeedsWrapper._value
            if (!feeds && s.search && s.search.searchFeedsWrapper && s.search.searchFeedsWrapper._value) {
                feeds = s.search.searchFeedsWrapper._value;
            }
            
            if (!feeds) {
                return JSON.stringify({error: 'Cannot find raw feeds', 
                    searchKeys: Object.keys(s.search || {}),
                    wrapperKeys: s.search.searchFeedsWrapper ? Object.keys(s.search.searchFeedsWrapper) : []
                });
            }
            
            var info = {
                type: typeof feeds,
                isArray: Array.isArray(feeds),
                length: feeds.length
            };
            
            if (feeds.length > 0) {
                var first = feeds[0];
                info.firstKeys = Object.keys(first);
                info.firstId = first.id || '(none)';
                info.firstXsecToken = first.xsec_token || '(none)';
                info.firstModelType = first.model_type || '(none)';
                
                if (first.note_card) {
                    info.noteCardKeys = Object.keys(first.note_card);
                    info.noteCardTitle = first.note_card.display_title || first.note_card.title || '(none)';
                    info.noteCardType = first.note_card.type || '(none)';
                    info.noteCardUser = first.note_card.user ? first.note_card.user.nickname : '(none)';
                }
                
                // Show first 3 items: id + xsec_token
                info.items = [];
                for (var i = 0; i < Math.min(feeds.length, 5); i++) {
                    var f = feeds[i];
                    info.items.push({
                        id: f.id || '(none)',
                        xsec_token: f.xsec_token || '(none)',
                        model_type: f.model_type || '(none)',
                        title: (f.note_card || {}).display_title || '(none)',
                        type: (f.note_card || {}).type || '(none)'
                    });
                }
            }
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message, stack: e.stack}); }
        """)
        print(f"Result: {r2}")

        # ===== Step 3: Scroll and re-check =====
        print("\n" + "=" * 70)
        print("STEP 3: Scroll down and re-check feeds")
        print("=" * 70)
        page.scroll.to_bottom()
        time.sleep(3)
        
        r3 = page.run_js("""
        try {
            var s = window.__INITIAL_STATE__;
            var feeds = null;
            if (s.search && s.search.searchFeedsWrapper) {
                feeds = s.search.searchFeedsWrapper._rawValue || s.search.searchFeedsWrapper._value;
            }
            
            var exploreLinks = document.querySelectorAll('a[href*="/explore/"]');
            var noteItems = document.querySelectorAll('.note-item');
            
            var info = {
                feedsLength: feeds ? feeds.length : -1,
                exploreLinksCount: exploreLinks.length,
                noteItemCount: noteItems.length,
            };
            
            // Sample explore links
            if (exploreLinks.length > 0) {
                info.sampleLinks = [];
                for (var i = 0; i < Math.min(exploreLinks.length, 5); i++) {
                    info.sampleLinks.push({
                        href: exploreLinks[i].getAttribute('href'),
                        className: exploreLinks[i].className.substring(0, 50),
                        parentClass: exploreLinks[i].parentElement ? exploreLinks[i].parentElement.className.substring(0, 50) : ''
                    });
                }
            }
            
            // Show feed data summary
            if (feeds && feeds.length > 0) {
                info.feedsSummary = [];
                for (var i = 0; i < Math.min(feeds.length, 3); i++) {
                    var f = feeds[i];
                    info.feedsSummary.push({
                        id: f.id,
                        xsec_token: (f.xsec_token || '').substring(0, 30) + '...',
                        title: ((f.note_card || {}).display_title || '').substring(0, 30),
                        type: (f.note_card || {}).type
                    });
                }
            }
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r3}")

        # ===== Step 4: Inspect actual DOM structure of note cards =====
        print("\n" + "=" * 70)
        print("STEP 4: Deep DOM inspection of .feeds-page children")
        print("=" * 70)
        r4 = page.run_js("""
        try {
            var container = document.querySelector('.feeds-page');
            if (!container) return 'No .feeds-page found';
            
            var info = {
                containerClass: container.className,
                childCount: container.children.length,
                children: []
            };
            
            for (var i = 0; i < Math.min(container.children.length, 5); i++) {
                var child = container.children[i];
                var childInfo = {
                    tag: child.tagName.toLowerCase(),
                    class: child.className.substring(0, 80),
                    id: child.id || '',
                    childCount: child.children.length,
                    // Check for any <a> in this child
                    links: []
                };
                var links = child.querySelectorAll('a');
                for (var j = 0; j < Math.min(links.length, 3); j++) {
                    childInfo.links.push({
                        href: (links[j].getAttribute('href') || '').substring(0, 100),
                        class: links[j].className.substring(0, 50)
                    });
                }
                info.children.push(childInfo);
            }
            
            return JSON.stringify(info, null, 2);
        } catch(e) { return JSON.stringify({error: e.message}); }
        """)
        print(f"Result: {r4}")

    finally:
        browser.disconnect()


if __name__ == '__main__':
    keyword = sys.argv[1] if len(sys.argv) > 1 else "新加坡求职"
    debug_search_page3(keyword)
