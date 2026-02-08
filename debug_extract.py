"""
Debug script: extract data from a single XHS note page.
Helps diagnose what data is available via JS and DOM.

Usage:
    python debug_extract.py <note_url>
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def debug_extract(url: str):
    browser = BrowserManager(login_wait=0)
    try:
        page = browser.page
        logger.info(f"Navigating to: {url}")
        page.get(url)
        time.sleep(3)

        logger.info(f"Current page URL: {page.url}")
        logger.info(f"Page title: {page.title}")

        # ===== Test 1: Check if __INITIAL_STATE__ exists =====
        print("\n" + "=" * 70)
        print("TEST 1: Check window.__INITIAL_STATE__ existence")
        print("=" * 70)

        check_js = """
        try {
            if (!window.__INITIAL_STATE__) return 'NOT_FOUND';
            var t = typeof window.__INITIAL_STATE__;
            var keys = Object.keys(window.__INITIAL_STATE__);
            return JSON.stringify({type: t, topKeys: keys});
        } catch(e) {
            return 'ERROR: ' + e.message;
        }
        """
        result1 = page.run_js(check_js)
        print(f"Result: {result1}")

        # ===== Test 2: Check note structure =====
        print("\n" + "=" * 70)
        print("TEST 2: Check note structure in __INITIAL_STATE__")
        print("=" * 70)

        check_note_js = """
        try {
            var state = window.__INITIAL_STATE__;
            if (!state) return 'STATE_NOT_FOUND';
            
            var info = {};
            info.hasNote = !!state.note;
            if (state.note) {
                info.noteKeys = Object.keys(state.note);
                info.hasNoteDetailMap = !!state.note.noteDetailMap;
                if (state.note.noteDetailMap) {
                    info.noteDetailMapKeys = Object.keys(state.note.noteDetailMap);
                    // Check first entry structure
                    var firstKey = Object.keys(state.note.noteDetailMap)[0];
                    if (firstKey) {
                        var entry = state.note.noteDetailMap[firstKey];
                        info.firstEntryKeys = Object.keys(entry);
                        if (entry.note) {
                            info.noteObjKeys = Object.keys(entry.note);
                        }
                    }
                }
                info.hasNoteDetail = !!state.note.noteDetail;
            }
            return JSON.stringify(info, null, 2);
        } catch(e) {
            return 'ERROR: ' + e.message;
        }
        """
        result2 = page.run_js(check_note_js)
        print(f"Result: {result2}")

        # ===== Test 3: Try to extract actual note data =====
        print("\n" + "=" * 70)
        print("TEST 3: Extract actual note data")
        print("=" * 70)

        extract_js = """
        try {
            var state = window.__INITIAL_STATE__;
            if (!state || !state.note) return JSON.stringify({error: 'no state.note'});

            // Try noteDetailMap first
            var noteMap = state.note.noteDetailMap;
            if (!noteMap) return JSON.stringify({error: 'no noteDetailMap', noteKeys: Object.keys(state.note)});

            var keys = Object.keys(noteMap);
            if (keys.length === 0) return JSON.stringify({error: 'noteDetailMap is empty'});

            var entry = noteMap[keys[0]];
            var n = entry.note || entry;
            if (!n) return JSON.stringify({error: 'no note in entry', entryKeys: Object.keys(entry)});

            var user = n.user || {};
            var interact = n.interactInfo || {};

            var result = {
                noteId: n.noteId || '(missing)',
                type: n.type || '(missing)',
                title: n.title || '(missing)',
                descLength: (n.desc || '').length,
                descPreview: (n.desc || '').substring(0, 200),
                userName: user.nickname || '(missing)',
                userId: user.userId || user.uid || '(missing)',
                likedCount: interact.likedCount,
                commentCount: interact.commentCount,
                collectedCount: interact.collectedCount,
                shareCount: interact.shareCount,
                time: n.time ? String(n.time) : '(missing)',
                ipLocation: n.ipLocation || '(missing)',
                imageCount: (n.imageList || []).length,
                tagCount: (n.tagList || []).length,
                tagNames: (n.tagList || []).map(function(t) { return t.name; })
            };
            return JSON.stringify(result, null, 2);
        } catch(e) {
            return JSON.stringify({error: e.message, stack: e.stack});
        }
        """
        result3 = page.run_js(extract_js)
        print(f"Result: {result3}")

        # ===== Test 4: Try the actual _JS_EXTRACT from extractor.py =====
        print("\n" + "=" * 70)
        print("TEST 4: Run actual _JS_EXTRACT from extractor.py")
        print("=" * 70)

        from crawler.extractor import _JS_EXTRACT
        result4 = page.run_js(_JS_EXTRACT)
        if result4:
            try:
                data = json.loads(result4) if isinstance(result4, str) else result4
                print(f"Extracted type: {type(data)}")
                print(f"Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                print(f"Title: {data.get('title', '(missing)')}")
                print(f"Desc preview: {(data.get('desc', '') or '')[:200]}")
                print(f"Interact: {data.get('interactInfo', {})}")
                print(f"Time: {data.get('time', '(missing)')}")
                print(f"Type: {data.get('type', '(missing)')}")
                print(f"Image count: {len(data.get('imageList', []))}")
                print(f"Tag count: {len(data.get('tagList', []))}")
            except Exception as e:
                print(f"Parse error: {e}")
                print(f"Raw result (first 500 chars): {str(result4)[:500]}")
        else:
            print(f"_JS_EXTRACT returned: {result4!r} (type: {type(result4)})")

        # ===== Test 5: DOM extraction attempts =====
        print("\n" + "=" * 70)
        print("TEST 5: DOM element checks")
        print("=" * 70)

        selectors_to_check = [
            ('Title #detail-title', '#detail-title'),
            ('Title .title', 'css:.note-detail .title'),
            ('Content #detail-desc', '#detail-desc'),
            ('Content .desc', 'css:.note-detail .desc'),
            ('Content note-text', 'css:.note-text'),
            ('Content [class*=desc]', 'css:[class*="desc"]'),
            ('Author .username', 'css:[class*="username"]'),
            ('Date .date', 'css:[class*="date"]'),
            ('Like .like-wrapper', 'css:[class*="like"]'),
            ('Comment .chat-wrapper', 'css:[class*="chat"]'),
        ]
        for label, sel in selectors_to_check:
            try:
                ele = page.ele(sel, timeout=2)
                if ele:
                    text = (ele.text or '')[:100]
                    print(f"  ✅ {label:30s} => '{text}'")
                else:
                    print(f"  ❌ {label:30s} => NOT FOUND")
            except Exception as e:
                print(f"  ❌ {label:30s} => ERROR: {e}")

        # ===== Test 6: Get page HTML snippet for analysis =====
        print("\n" + "=" * 70)
        print("TEST 6: Page source snippet (first 3000 chars of body)")
        print("=" * 70)
        try:
            body_html = page.run_js("return document.body.innerHTML.substring(0, 3000);")
            print(body_html)
        except Exception as e:
            print(f"Error: {e}")

    finally:
        browser.disconnect()


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.xiaohongshu.com/explore/6974af28000000002103171d"
        "?xsec_token=ABX_z6LFrZ5v_xguF5dlCdx-MxiYXIwYzAjBFd83SgZJ0="
        "&xsec_source=pc_feed"
    )
    debug_extract(url)
