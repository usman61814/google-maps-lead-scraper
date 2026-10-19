# Google Maps Lead Scraper

A desktop tool that searches Google Maps for businesses (for example *"pet care services in Multan"*) and saves each result's **name, phone number, website, address and Maps link** to a CSV file. It is meant for building sales-lead lists.

It drives **Camoufox**, a stealth build of Firefox controlled through Playwright, so the browser looks like a normal visitor. It comes with a simple **Tkinter window** and a **command-line interface**.

## Features

- Search one or many keywords in one run (one per line, or from a text file)
- Choose how many leads to collect per keyword
- Choose which columns to save
- Filter leads, for example "only businesses **without** a website" or "only businesses **with** a phone number"
- Saves after every lead, so a crash or a Stop never loses collected data
- Skips duplicate listings across keywords
- Human-like behaviour: random delays, typing one character at a time, human cursor movement, a random OS fingerprint and window size per run
- CAPTCHA handling: the app beeps, shows a desktop notification and waits up to 10 minutes while you solve the CAPTCHA in the browser window

## Project structure

| File | Purpose |
|---|---|
| `maps_stealth_scraper.py` | The scraping engine and the command-line interface |
| `app.py` | The Tkinter desktop window that runs the engine in a background thread |
| `Start Lead Scraper.bat` | Double-click launcher for Windows (opens the window without a console) |
| `requirements.txt` | Python dependencies |
| `generated/` | Output folder where CSV files are written (created automatically, not committed) |

## Setup

Requires Python 3.9+.

```
pip install -r requirements.txt
python -m camoufox fetch
```

The second command downloads the Camoufox browser itself (one time only).

## Usage

### Desktop window

Double-click `Start Lead Scraper.bat`, or run:

```
python app.py
```

1. Type one search per line, e.g. `dentists in Lahore`.
2. Set **Leads per keyword** and the **Output file** name.
3. Untick any columns you don't want.
4. Optionally set filters (Website / Phone: Any, Has it, Missing).
5. Click **Start**. Progress shows in the log box. **Stop** ends the run early and keeps what was collected.
6. Click **Open results folder** to see the CSV.

Leave **Hide browser** unticked if you want to be able to solve CAPTCHAs.

### Command line

```
python maps_stealth_scraper.py "pet care services in Multan" -n 50
python maps_stealth_scraper.py --keywords-file keywords.txt -n 10 --headless
```

| Option | Meaning |
|---|---|
| `query` | Search text (optional if `--keywords-file` is given) |
| `--keywords-file` | Text file with one query per line; lines starting with `#` are ignored |
| `-n`, `--count` | Maximum leads per query (default 15) |
| `-o`, `--output` | CSV file name inside `generated/` (default `gmaps_leads.csv`) |
| `--headless` | Hide the browser (a CAPTCHA will then stop the run) |

### Output

A UTF-8 CSV (with BOM, so Excel opens it correctly) in `generated/` with these columns:

`Business Name, Phone Number, Website Link, Address, Google Maps Link`

Missing values are written as `N/A`.

## How it works

The scraper runs in two stages for each keyword:

1. **Collect listings.** It opens Google Maps, types the search, then scrolls the results panel and gathers each listing's name and link until it has enough or reaches the end of the list.
2. **Extract details.** It opens each listing's page and reads the phone, website and address. Leads that don't pass the filters are dropped. Each kept lead is appended to the CSV immediately.

When filters are on, it collects four times as many candidate listings, because many will be filtered out.

---

## Code walkthrough, line by line

### `maps_stealth_scraper.py` (scraping engine)

**Module docstring and imports (lines 1–22)**

| Lines | Code | Explanation |
|---|---|---|
| 1–6 | `"""Google Maps lead scraper ..."""` | Describes the module and shows two example commands. |
| 7 | `import argparse` | Parses command-line options. |
| 8 | `import csv` | Writes the results file. |
| 9 | `import logging` | Progress messages, shown in the console or in the UI log box. |
| 10 | `import random` | Random delays, random OS and window size. |
| 11 | `import re` | Regular expression used to unwrap Google redirect links. |
| 12 | `import threading` | Provides the `Event` used to stop a run from the UI. |
| 13 | `import time` | Sleeps between keystrokes and measures the CAPTCHA timeout. |
| 14 | `from pathlib import Path` | File paths for the output folder. |
| 15 | `from urllib.parse import quote_plus, unquote` | Encodes a query into a URL; decodes a website URL. |
| 17 | `from camoufox.sync_api import Camoufox` | The stealth Firefox browser (synchronous Playwright API). |
| 19–22 | `try: import winsound ... except ImportError: winsound = None` | `winsound` exists only on Windows. On other systems it is set to `None` so the beep is skipped instead of crashing. |

**Logging and constants (lines 24–36)**

| Lines | Code | Explanation |
|---|---|---|
| 24 | `logging.basicConfig(...)` | Prints log messages with time and level to the console. |
| 25 | `log = logging.getLogger("maps")` | Named logger; `app.py` attaches its own handler to it to show messages in the window. |
| 27 | `SEARCH_BOX = 'input[name="q"]'` | CSS selector for the Maps search box. |
| 28 | `FEED = '[role="feed"]'` | The scrollable results panel on the left. |
| 29 | `PLACE_LINK = 'a[href*="/maps/place/"]'` | Every link that points to a business page. |
| 30 | `CAPTCHA_SELECTOR = ...` | iframes from reCAPTCHA or Arkose Labs, which mean Google is challenging the browser. |
| 31 | `OUTPUT_DIR = Path("generated")` | Folder where CSVs are written. |
| 32 | `COLUMNS = [...]` | The five output columns, in order. |
| 33 | `RESOLUTIONS = [...]` | Common real-world screen sizes; one is picked per run. |
| 34 | `OS_CHOICES = ["windows", "macos"]` | Operating systems the browser fingerprint can pretend to be. |
| 36 | `STOP = threading.Event()` | A shared flag. The UI's Stop button sets it and the scraper checks it during every wait. |

**`Stopped` exception (lines 39–40)**

A custom exception raised when the user presses Stop. It unwinds the scraping loops cleanly so the `finally` block can still save the results.

**`human_delay(lo, hi)` (lines 43–45)**

Waits a random number of seconds between `lo` and `hi`. It uses `STOP.wait(...)` instead of `time.sleep(...)`, so the wait ends immediately when Stop is pressed. If it returns `True` (Stop was pressed), it raises `Stopped`.

**`is_captcha(page)` (lines 48–52)**

Returns `True` if the current URL contains `/sorry/` (Google's "unusual traffic" page) or a CAPTCHA iframe is on the page. Any error (for example while the page is loading) is treated as "no CAPTCHA".

**`alert_user()` (lines 55–64)**

| Lines | Explanation |
|---|---|
| 57–59 | On Windows, beeps three times (1200 Hz, 0.4 s each). |
| 60–64 | Tries to show a desktop notification with `plyer`. If `plyer` isn't installed or fails, it is silently skipped. |

**`wait_if_blocked(page, headless)` (lines 67–82)**

| Lines | Explanation |
|---|---|
| 69–70 | If there is no CAPTCHA, return immediately. |
| 71–72 | In headless mode the user can't see the browser, so the run stops with an error. |
| 73–74 | Logs a warning and alerts the user. |
| 75 | Sets a deadline 600 seconds (10 minutes) from now. |
| 76–80 | Checks every 2 seconds whether the CAPTCHA is gone. It gives up after the deadline and exits if Stop is pressed. |
| 81–82 | Logs success and pauses briefly before continuing. |

**`search(page, query, headless)` (lines 85–107)**

| Lines | Explanation |
|---|---|
| 86 | Opens `google.com/maps`. |
| 87–88 | Waits 3–5 seconds, then checks for a CAPTCHA. |
| 89–93 | Clicks "Accept all" or "I agree" on the cookie consent screen if one appears; otherwise continues. |
| 95 | Logs the search. |
| 97 | Waits up to 30 s for the search box to exist. |
| 98 | Clicks the search box. |
| 99–101 | Types the query one character at a time with random 40–180 ms pauses, like a person. |
| 102 | Presses Enter. |
| 103–105 | If the search box can't be used, opens the search results URL directly instead. |
| 106–107 | Waits for the results to load and checks for a CAPTCHA again. |

**`collect_listings(page, query, target, headless, max_scrolls=30)` (lines 110–129)**

Stage 1: collects listing names and links.

| Lines | Explanation |
|---|---|
| 112 | Runs the search. |
| 113–117 | Waits up to 15 s for the results panel. If there isn't one (a single exact match, or no results), returns an empty list. |
| 119 | `stubs` is a dict of `url → name`; using the URL as key removes duplicates. |
| 120 | Scrolls up to `max_scrolls` times. |
| 121–123 | Runs JavaScript in the page to read every place link's `aria-label` (the business name) and `href`, and stores new ones. |
| 124 | Logs how many listings have been found so far. |
| 125–126 | Stops when there are enough listings or Google shows "You've reached the end of the list". |
| 127 | Scrolls the results panel to the bottom, which makes Maps load more results. |
| 128 | Waits 2.5–4 s for them to load. |
| 129 | Returns at most `target` `(name, url)` pairs. |

**`attr(page, selector, name)` (lines 132–134)**

A helper that returns an attribute of the first element matching `selector`, or `""` if no such element exists. The 1-second timeout keeps it from hanging on missing elements.

**`extract_details(page, name, url, headless)` (lines 137–149)**

Stage 2: reads one business's details.

| Lines | Explanation |
|---|---|
| 139–141 | Opens the listing page, waits 3.5–5.5 s, checks for a CAPTCHA. |
| 143 | The phone number is stored in an attribute like `data-item-id="phone:tel:+92300..."`; the prefix is removed. |
| 144 | The website button's link. |
| 145–147 | Google sometimes wraps the website in a redirect (`...?q=https://real-site.com&...`). This pulls out and decodes the real URL. |
| 148 | The address comes from the address button's `aria-label`; the `Address:` prefix is removed. |
| 149 | Builds a dict mapping each column name to its value, using `N/A` for anything missing. |

**`matches(lead, filters)` (lines 152–154)**

Checks a lead against the filters. `filters` looks like `{"Website Link": "missing"}`. For each rule, "has" requires the value to not be `N/A` and "missing" requires it to be `N/A`. All rules must pass.

**`save(rows, path, fields)` (lines 157–162)**

| Lines | Explanation |
|---|---|
| 158 | Creates `generated/` if needed. |
| 159 | Opens the file with `utf-8-sig` encoding, which adds a BOM so Excel shows non-English characters correctly. |
| 160 | `DictWriter` writes only the chosen `fields`; `extrasaction="ignore"` drops the other columns. |
| 161–162 | Writes the header row and all leads. The whole file is rewritten each time, so it is always complete. |

**`scrape(queries, target_count, output_file, headless, fields, filters)` (lines 165–228)**

The main function, used by both the CLI and the UI.

| Lines | Explanation |
|---|---|
| 167 | Clears the Stop flag from any earlier run. |
| 168 | Keeps the selected fields in the standard column order. Defaults to all columns. |
| 169 | Defaults to no filters. |
| 170 | Full output path, e.g. `generated/leads.csv`. |
| 171 | `leads` holds kept results; `seen` holds already-visited URLs so a business found by two keywords is visited once. |
| 172–173 | Logs the active filters. |
| 174–175 | Picks a random OS and window size for this run and logs them. |
| 178–185 | Starts Camoufox with: the visible/hidden setting, the chosen OS fingerprint, a realistic window size (Camoufox's own random sizes can hide the results panel), WebRTC blocked so the real IP can't leak, and human-like mouse movement. |
| 186 | Opens a tab. |
| 187 | Loops over each keyword. |
| 189 | With filters, aims to collect four times as many candidates. |
| 190–196 | Runs stage 1. CAPTCHA failures and Stop are passed up; any other error skips this keyword. |
| 198 | Counts kept leads for this keyword. |
| 199–201 | Goes through the listings, stopping once enough leads are kept. |
| 202–204 | Skips URLs already visited and marks the rest as visited. |
| 205 | Logs progress, e.g. `[dentists in Lahore 3/20] Smile Clinic`. |
| 206–212 | Runs stage 2. CAPTCHA failures and Stop are passed up; any other error skips that business. |
| 213–215 | Drops leads that fail the filters. |
| 216–218 | Keeps the lead and logs the count. |
| 219 | Saves the CSV right away. |
| 220–221 | Logs if fewer matching leads than requested were found. |
| 222 | Waits 5–10 s before the next keyword. |
| 223–224 | If Stop was pressed, logs it and carries on to the save. |
| 225–226 | `finally` always saves the results, even after an error. |
| 227–228 | Logs the total and returns the leads. |

**`main()` (lines 231–247)** — command-line entry point

| Lines | Explanation |
|---|---|
| 232–237 | Defines the options: optional `query`, `--keywords-file`, `-n/--count`, `-o/--output`, `--headless`. |
| 238 | Reads the options. |
| 240 | Starts the query list with the positional query, if given. |
| 241–243 | Adds each non-empty line of the keywords file, skipping lines that start with `#`. |
| 244–245 | Shows an error if there are no queries. |
| 247 | Runs the scraper. |

**Lines 250–251** — `if __name__ == "__main__": main()` runs `main()` only when the file is executed directly, not when `app.py` imports it.

---

### `app.py` (desktop window)

**Imports and constants (lines 1–11)**

| Lines | Code | Explanation |
|---|---|---|
| 1 | docstring | Describes the file. |
| 2 | `import logging` | To capture the scraper's log messages. |
| 3 | `import os` | `os.startfile` opens the results folder in Explorer. |
| 4 | `import queue` | Thread-safe queue for passing log lines from the worker thread to the window. |
| 5 | `import threading` | Runs the scraper in the background so the window stays responsive. |
| 6–7 | `tkinter` imports | The GUI toolkit, message boxes and a scrollable text box. |
| 9 | `import maps_stealth_scraper as scraper` | The scraping engine. |
| 11 | `FILTER_OPTIONS` | Maps dropdown labels to filter rules: "Any" means no filter, "Has it" → `"has"`, "Missing" → `"missing"`. |

**`QueueHandler` (lines 14–20)**

A logging handler that puts each formatted log message into a queue instead of printing it. Tkinter widgets may only be changed from the main thread, so the worker thread puts messages in the queue and the main thread reads them out.

**`App.__init__` (lines 23–83)** — builds the window

| Lines | Explanation |
|---|---|
| 25–27 | Creates the window, sets its title and size (820×620). |
| 28–29 | Creates the log queue; no worker thread yet. |
| 31–33 | Creates a `QueueHandler` with a `time  message` format and attaches it to the scraper's logger. |
| 35–37 | Label and multi-line text box for the keywords. |
| 39–40 | A horizontal row for the main settings. |
| 41–45 | "Leads per keyword" number box (1–500), default 20. |
| 46–49 | "Output file" text box, default `leads.csv`. |
| 50–51 | "Hide browser" checkbox, unticked by default. |
| 53–59 | "Fields to save" row: Business Name is always saved; one checkbox for each other column (`COLUMNS[1:]`), all ticked. |
| 61–68 | "Only keep leads where" row: dropdowns for Website and Phone, each Any / Has it / Missing. |
| 70–76 | Buttons: Start, Stop (disabled until a run starts), Open results folder. |
| 77–78 | Status label on the right, "Idle" in grey. |
| 80–81 | Read-only scrolling log box that fills the rest of the window. |
| 83 | Schedules `pump_logs` to run in 200 ms. |

**`start()` (lines 85–107)** — runs when Start is clicked

| Lines | Explanation |
|---|---|
| 86 | Reads the keywords, one per non-empty line. |
| 87–89 | Warns and returns if there are none. |
| 90–94 | Reads the lead count; warns if it isn't a number. |
| 95–97 | Reads the file name, defaults to `leads.csv`, and adds `.csv` if missing. |
| 98 | Fields to save: Business Name plus every ticked column. |
| 99 | Filters: only the dropdowns not set to "Any". |
| 101–103 | Disables Start, enables Stop, sets status to "Running..." in green. |
| 104–107 | Starts `run_job` in a daemon thread (it won't keep the app open after the window is closed). |

**`run_job(...)` (lines 109–114)**

Runs in the background thread. Calls `scraper.scrape(...)`, puts any error into the log, then always puts the special `__DONE__` marker so the window knows the run ended.

**`stop()` (lines 116–118)**

Sets the scraper's `STOP` flag and shows "Stopping..." in orange. The scraper stops at its next wait and saves what it has.

**`open_folder()` (lines 120–122)**

Creates `generated/` if needed and opens it in Windows Explorer.

**`pump_logs()` (lines 124–136)**

Runs on the main thread every 200 ms.

| Lines | Explanation |
|---|---|
| 125–126 | Takes every waiting message from the queue. |
| 127–131 | On `__DONE__`, re-enables Start, disables Stop and sets status back to "Idle". |
| 132–135 | Otherwise unlocks the log box, appends the line, scrolls to the bottom and locks it again. |
| 136 | Schedules itself again in 200 ms. |

**Lines 139–140** — create the window and start the Tkinter event loop.

---

### `Start Lead Scraper.bat`

| Line | Code | Explanation |
|---|---|---|
| 1 | `@echo off` | Don't print the commands. |
| 2 | `rem ...` | Comment. |
| 3 | `cd /d "%~dp0"` | Switch to the folder containing this .bat file (`%~dp0`), even on another drive (`/d`), so `generated/` is created next to the code. |
| 4 | `start "" pythonw app.py` | Start the app with `pythonw`, which has no console window. |

### `requirements.txt`

| Package | Purpose |
|---|---|
| `camoufox` | Stealth Firefox plus Playwright for browser automation |
| `plyer` | Cross-platform desktop notifications for CAPTCHA alerts |

## Notes

- Google Maps changes its page layout from time to time. If fields come back as `N/A`, the CSS selectors near the top of `maps_stealth_scraper.py` may need updating.
- Use the tool responsibly and in line with Google's Terms of Service and local data-protection laws.
