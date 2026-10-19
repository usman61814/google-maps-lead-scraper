"""Google Maps lead scraper built on Camoufox (stealth Firefox).

Usage:
    python maps_stealth_scraper.py "pet care services in Multan" -n 50
    python maps_stealth_scraper.py --keywords-file keywords.txt -n 10 --headless
"""
import argparse
import csv
import logging
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus, unquote

from camoufox.sync_api import Camoufox

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("maps")

SEARCH_BOX = 'input[name="q"]'
FEED = '[role="feed"]'
PLACE_LINK = 'a[href*="/maps/place/"]'
CAPTCHA_SELECTOR = 'iframe[src*="recaptcha"], iframe[src*="arkoselabs"]'
OUTPUT_DIR = Path("generated")
COLUMNS = ["Business Name", "Phone Number", "Website Link", "Address", "Google Maps Link"]
RESOLUTIONS = [(1920, 1080), (1536, 864), (1440, 900), (1366, 768)]
OS_CHOICES = ["windows", "macos"]

STOP = threading.Event()  # set by the UI to stop a run


class Stopped(Exception):
    pass


def human_delay(lo, hi):
    if STOP.wait(random.uniform(lo, hi)):
        raise Stopped()


def is_captcha(page):
    try:
        return "/sorry/" in page.url or page.locator(CAPTCHA_SELECTOR).count() > 0
    except Exception:
        return False


def alert_user():
    """Beep and pop a desktop notification so the user knows to come back."""
    if winsound:
        for _ in range(3):
            winsound.Beep(1200, 400)
    try:
        from plyer import notification
        notification.notify(title="Scraper paused", message="CAPTCHA solver needed - solve it in the browser.", timeout=10)
    except Exception:
        pass


def wait_if_blocked(page, headless):
    """On a CAPTCHA, alert the user and wait (up to 10 min) until they solve it in the window."""
    if not is_captcha(page):
        return
    if headless:
        raise RuntimeError("Google showed a CAPTCHA. Re-run with the browser visible and solve it manually.")
    log.warning("CAPTCHA detected - solve it in the browser window (waiting up to 10 minutes)...")
    alert_user()
    deadline = time.time() + 600
    while is_captcha(page):
        if time.time() > deadline:
            raise RuntimeError("CAPTCHA was not solved within 10 minutes.")
        if STOP.wait(2):
            raise Stopped()
    log.info("CAPTCHA solved, continuing.")
    human_delay(2, 4)


def search(page, query, headless):
    page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
    human_delay(3, 5)
    wait_if_blocked(page, headless)
    try:
        page.locator('button:has-text("Accept all"), button:has-text("I agree")').first.click(timeout=3000)
        human_delay(2, 4)
    except Exception:
        pass  # no cookie wall

    log.info("Searching: %s", query)
    try:
        page.locator(SEARCH_BOX).first.wait_for(state="attached", timeout=30000)
        page.click(SEARCH_BOX)
        for ch in query:  # irregular human typing
            page.keyboard.type(ch)
            time.sleep(random.uniform(0.04, 0.18))
        page.keyboard.press("Enter")
    except Exception:
        log.warning("Search box not usable; opening the search URL directly.")
        page.goto("https://www.google.com/maps/search/" + quote_plus(query), wait_until="domcontentloaded")
    human_delay(5, 7)
    wait_if_blocked(page, headless)


def collect_listings(page, query, target, headless, max_scrolls=30):
    """Stage 1: search and scroll the results feed, returning (name, url) pairs."""
    search(page, query, headless)
    try:
        page.wait_for_selector(FEED, timeout=15000)
    except Exception:
        log.warning("No results feed for %r (single result or no matches).", query)
        return []

    stubs = {}
    for step in range(1, max_scrolls + 1):
        for name, url in page.eval_on_selector_all(PLACE_LINK, "els => els.map(a => [a.getAttribute('aria-label'), a.href])"):
            if name and url:
                stubs.setdefault(url, name)
        log.info("Scroll %d: %d listings", step, len(stubs))
        if len(stubs) >= target or page.get_by_text("You've reached the end of the list").count():
            break
        page.eval_on_selector(FEED, "el => el.scrollTop = el.scrollHeight")
        human_delay(2.5, 4.0)
    return [(name, url) for url, name in stubs.items()][:target]


def attr(page, selector, name):
    el = page.locator(selector).first
    return (el.get_attribute(name, timeout=1000) or "") if el.count() else ""


def extract_details(page, name, url, headless):
    """Stage 2: open one listing and read phone / website / address."""
    page.goto(url, wait_until="domcontentloaded")
    human_delay(3.5, 5.5)
    wait_if_blocked(page, headless)

    phone = attr(page, '[data-item-id^="phone:tel:"]', "data-item-id").replace("phone:tel:", "")
    website = attr(page, 'a[data-item-id="authority"]', "href")
    m = re.search(r"[?&]q=([^&]+)", website)  # unwrap google redirect links
    if m:
        website = unquote(m.group(1))
    address = attr(page, '[data-item-id="address"]', "aria-label").replace("Address:", "")
    return dict(zip(COLUMNS, [name, phone.strip() or "N/A", website or "N/A", address.strip() or "N/A", url]))


def matches(lead, filters):
    """filters: {column: "has" | "missing"}; columns not listed are not checked."""
    return all((lead[col] != "N/A") == (rule == "has") for col, rule in filters.items())


def save(rows, path, fields):
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def scrape(queries, target_count=15, output_file="gmaps_leads.csv", headless=False, fields=None, filters=None):
    """fields: columns to save (default all). filters: e.g. {"Website Link": "missing"}."""
    STOP.clear()
    fields = [c for c in COLUMNS if c in (fields or COLUMNS)]
    filters = filters or {}
    path = OUTPUT_DIR / output_file
    leads, seen = [], set()
    if filters:
        log.info("Filters: %s", ", ".join(f"{c} = {r}" for c, r in filters.items()))
    os_name, window = random.choice(OS_CHOICES), random.choice(RESOLUTIONS)
    log.info("Browser profile: %s, %dx%d", os_name, *window)

    # Camoufox rotates fingerprints (fonts, WebGL, canvas, ...) and blocks WebRTC IP leaks.
    try:
        with Camoufox(
            headless=headless,
            os=os_name,
            window=window,  # realistic size; Camoufox's own random sizes can hide the results panel
            block_webrtc=True,
            humanize=True,  # human-like cursor movement
        ) as browser:
            page = browser.new_page()
            for query in queries:
                # With filters, many listings get rejected, so gather extra candidates.
                pool = target_count * 4 if filters else target_count
                try:
                    stubs = collect_listings(page, query, pool, headless, max_scrolls=60 if filters else 30)
                except (RuntimeError, Stopped):
                    raise
                except Exception as exc:
                    log.error("Search failed for %r: %s", query, exc)
                    continue

                found = 0
                for i, (name, url) in enumerate(stubs, 1):
                    if found >= target_count:
                        break
                    if url in seen:
                        continue
                    seen.add(url)
                    log.info("[%s %d/%d] %s", query, i, len(stubs), name)
                    try:
                        lead = extract_details(page, name, url, headless)
                    except (RuntimeError, Stopped):
                        raise
                    except Exception as exc:
                        log.error("Skipped %s: %s", name, exc)
                        continue
                    if not matches(lead, filters):
                        log.info("    filtered out")
                        continue
                    leads.append(lead)
                    found += 1
                    log.info("    kept (%d/%d)", found, target_count)
                    save(leads, path, fields)  # incremental save so a crash never loses work
                if found < target_count:
                    log.info("Only %d matching leads found for %r.", found, query)
                human_delay(5, 10)
    except Stopped:
        log.info("Stopped by user.")
    finally:
        save(leads, path, fields)
    log.info("Finished. %d leads saved to %s", len(leads), path)
    return leads


def main():
    ap = argparse.ArgumentParser(description="Google Maps lead scraper (Camoufox)")
    ap.add_argument("query", nargs="?", help='Search text, e.g. "Plumber London"')
    ap.add_argument("--keywords-file", help="Text file with one search query per line")
    ap.add_argument("-n", "--count", type=int, default=15, help="Max leads per query")
    ap.add_argument("-o", "--output", default="gmaps_leads.csv", help="CSV name inside generated/")
    ap.add_argument("--headless", action="store_true", help="Hide the browser (CAPTCHAs can't be solved)")
    args = ap.parse_args()

    queries = [args.query] if args.query else []
    if args.keywords_file:
        lines = Path(args.keywords_file).read_text(encoding="utf-8").splitlines()
        queries += [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    if not queries:
        ap.error("give a query or --keywords-file")

    scrape(queries, args.count, args.output, args.headless)


if __name__ == "__main__":
    main()
