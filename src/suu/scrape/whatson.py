from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup
import concurrent.futures
from .browser import get_selenium_driver

BASE_URL = "https://studentsunionucl.org/whats-on"
UK_TZ = ZoneInfo("Europe/London")

# Clock formats the What's On list view actually uses, tried in order and
# matched strictly. Anything matching none of them is "no time was given",
# not midnight — see _parse_time_range.
_CLOCK_FORMATS = ("%H:%M", "%H.%M", "%I:%M%p", "%I%p")

# Per-page fetch retries in enrich_event_details, and seconds of linear
# backoff between them. See fetch_description.
_FETCH_ATTEMPTS = 3
_FETCH_BACKOFF = 1.5

# Concurrent page fetches. Ten was enough to get a Welcome Week page
# throttled wholesale; five plus the retry above got every listing.
_FETCH_WORKERS = 5


def _parse_clock(text, date_obj):
    """Combine a clock string ("18:30", "6pm") with `date_obj`, or None.

    None means "this isn't a time", and the caller must not substitute one.
    """
    candidate = re.sub(r"\s+", "", str(text or "")).lower()
    if not candidate:
        return None
    for fmt in _CLOCK_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt).time()
        except ValueError:
            continue
        return datetime.combine(date_obj, parsed, tzinfo=UK_TZ)
    return None


def _parse_time_range(time_str, date_obj):
    """(start, end) for one listing's time text. Either may be None.

    Times are never invented. A row with no `.list-item--time` element, or
    with text that isn't a clock time, returns (None, None) — it used to
    fall through to a 00:00 -> 23:59 pair, which is indistinguishable from a
    genuine all-day listing and accounted for 181 of the 191 events
    production held longer than twelve hours (73 of which swallowed other
    events whole on the calendar).

    A single time with no dash ("18:30") is a known start with an unknown
    end, so it keeps its start rather than being discarded.

    An end at or before its start has run past midnight ("18:30 - 00:00"),
    so it rolls onto the next day. Both ends used to be combined with the
    same date, which is where production's 80 rows with endTime <= startTime
    came from.
    """
    text = str(time_str or "").replace("\u2013", "-").replace("\u2014", "-").strip()
    if not text:
        return None, None

    parts = [part.strip() for part in text.split("-")]
    start_dt = _parse_clock(parts[0], date_obj)
    if start_dt is None:
        return None, None

    end_dt = _parse_clock(parts[1], date_obj) if len(parts) > 1 else None
    if end_dt is not None and end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt

_SR_ONLY_SUFFIX = re.compile(r"\s*\(opens in a new tab\)\s*$", re.IGNORECASE)


def _clean_title(text):
    """The listing's title without the screen-reader text glued to it.

    Each card's title now ends in a `.visually-hidden` span reading
    "(opens in a new tab)". It is positioned off-screen rather than hidden,
    so Selenium counts it as rendered text and every scraped title came
    back as "Karaoke @ Phineas\\n(opens in a new tab)" — including the ones
    written to CSV and uploaded to Supabase.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return _SR_ONLY_SUFFIX.sub("", cleaned).strip()


def parse_event_tags(soup):
    """The SU's own tags for one listing, from its event page's soup.

    Every listing page carries a taxonomy field —
    `.field--name-field-event-tags` — holding a link per tag: "Social Impact",
    "Volunteering", "Free", "Under 18 Friendly", and so on. It is the SU's own
    vocabulary rather than anything inferred from the title, which makes it the
    one place a What's On event says what *kind* of thing it is.

    Each tag comes back as `{"slug", "label"}`. The slug is the **last** path
    segment of the href, because the taxonomy is not flat: "Social Impact" is
    `/tags/content/social-impact` while "Volunteering" is `/tags/volunteering`,
    and a consumer matching on a fixed prefix would see one and miss the other.
    The label is the link text as written, for anything that displays them.

    An empty list means "the page said nothing", which includes the case where
    the page was never readable at all (login-gated volunteering listings all
    redirect anonymous requests). It is not evidence that the event is
    untagged, and must not be scored as such.
    """
    tags = []
    seen = set()
    for link in soup.select(".field--name-field-event-tags a[href]"):
        href = (link.get("href") or "").strip()
        if "/tags/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1].strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        tags.append({"slug": slug, "label": link.get_text(strip=True)})
    return tags


class WhatsOnScraper:
    def __init__(self, start_date=None, end_date=None):
        uk_now = datetime.now(UK_TZ)
        self.start_date = start_date or uk_now.strftime("%Y-%m-%d")
        self.end_date = end_date or (uk_now + timedelta(days=7)).strftime("%Y-%m-%d")
        self.events = []

    def fetch_description(self, session, event):
        """
        Helper to fetch the description *and the tags* for a single event.

        Both live on the listing's own page and nowhere else — the list view
        the calendar is scraped from carries a title, a time, a venue and a
        group, and that is all.

        Neither is guaranteed. A `/whats-on/volunteering/...` listing answers
        302 to `/user/login` for an anonymous request, so the whole page is
        unreachable and the event keeps the fallback description it was built
        with and an empty tag list. That is why a consumer must not treat
        "no tags" as "not tagged"; see `parse_event_tags`.
        """
        try:
            url = event['link']

            # Retried, because a busy week is exactly when this fails. A
            # single attempt at ten-way concurrency is enough for the SU to
            # start refusing: a run over Welcome Week 2026 lost the tags for
            # 39 of 41 listings on one page, all of which answered 200 on a
            # slower serial retry. The events kept their fallback description
            # and an empty tag list, which is indistinguishable from a
            # genuinely untagged event — so a caller filtering on tags
            # silently dropped them.
            resp = None
            for attempt in range(_FETCH_ATTEMPTS):
                resp = session.get(url, timeout=15)
                if resp.status_code == 200:
                    break
                if attempt < _FETCH_ATTEMPTS - 1:
                    time.sleep(_FETCH_BACKOFF * (attempt + 1))

            if resp is None or resp.status_code != 200:
                status = resp.status_code if resp is not None else "no response"
                print(f"Failed to fetch {url}: {status}")
                return

            soup = BeautifulSoup(resp.text, 'html.parser')

            event['tags'] = parse_event_tags(soup)

            # Strategy 1: Standard Body
            body = soup.select_one(".field--name-body")
            if body:
                text = body.get_text(separator='\n', strip=True)
                if text:
                    event['description'] = text
                    return

            # Strategy 2: Node Content fallback
            content = soup.select_one(".node__content")
            if content:
                text = content.get_text(separator='\n', strip=True)
                if text:
                    event['description'] = text

        except Exception as e:
            print(f"Error fetching description for {event.get('title')}: {e}")

    def enrich_event_details(self, events):
        """
        Visit each event link PARALLELLY to extract full description.

        Fetched once per unique link, not once per event: a recurring series
        now emits one event per day-header (they all share one page), and
        re-fetching the same URL five times would be five times the load on
        the SU for one description.
        """
        if not events: return

        by_link = {}
        for event in events:
            by_link.setdefault(event.get('link'), []).append(event)
        representatives = [group[0] for group in by_link.values()]

        print(
            f"Enriching {len(events)} events "
            f"({len(representatives)} unique pages) with details in parallel..."
        )

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })

            with concurrent.futures.ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as executor:
                futures = [executor.submit(self.fetch_description, session, event) for event in representatives]
                concurrent.futures.wait(futures)

        # Every date of a recurring series shares one page, so it shares one
        # description *and one tag list*. Tags were left behind when this
        # copied only the description: day one of a series carried them and
        # every later occurrence looked untagged.
        for group in by_link.values():
            description = group[0].get('description')
            tags = group[0].get('tags') or []
            for sibling in group[1:]:
                sibling['description'] = description
                sibling['tags'] = list(tags)

    def scrape(self):
        print(f"Scraping What's On from {self.start_date} to {self.end_date}...")
        driver = get_selenium_driver(headless=True)
        wait = WebDriverWait(driver, 10)

        url = f"{BASE_URL}?s={self.start_date}&e={self.end_date}"

        try:
            driver.get(url)
            time.sleep(5) # Let JS load

            # Wait for React to mount
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".whats-on-container")))
            except:
                print("Container not found within 10s.")

            # 1. Force Date Update
            try:
                date_input = driver.find_element(By.CSS_SELECTOR, "input.whats-on-datepicker")
                if date_input:
                    driver.execute_script("""
                        let input = arguments[0];
                        let dateStr = arguments[1];
                        let lastValue = input.value;
                        input.value = dateStr;
                        let event = new Event('input', { bubbles: true });
                        event.simulated = true;
                        let tracker = input._valueTracker;
                        if (tracker) {
                            tracker.setValue(lastValue);
                        }
                        input.dispatchEvent(event);
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    """, date_input, self.start_date)
                    time.sleep(3) # Wait for update
            except Exception as e:
                print(f"Failed to set date input: {e}")

            # 2. Switch to List View
            #
            # The view switcher is a MUI ToggleButtonGroup whose buttons carry
            # an icon `<svg>` followed by a non-breaking space and the label
            # ("\xa0List"). Matching on the text was how this used to find it,
            # and the nbsp broke it — silently, because the `except` below
            # leaves the scraper in Week view, where `.day-header` and
            # `.card-grid` don't exist and every run reports zero events.
            # `value` and `aria-label` are what the widget is actually keyed
            # on, so match those and click via JS (the button is a
            # ToggleButton; a native click can land on the child svg).
            try:
                list_btn = driver.find_element(
                    By.CSS_SELECTOR, 'button[value="list"], button[aria-label="List"]'
                )
                driver.execute_script("arguments[0].click()", list_btn)
                time.sleep(2)
            except Exception as e:
                print(f"Could not find/click List button ({e}). Staying in Week view.")

            # 3. Navigate to the correct week (fallback if the date input didn't
            # actually move the calendar — click "Next" until the first visible
            # day-header reaches the target start date).
            target_start = datetime.strptime(self.start_date, "%Y-%m-%d").date()
            max_nav_clicks = 5

            for _ in range(max_nav_clicks):
                try:
                    first_header = driver.find_element(By.CSS_SELECTOR, ".day-header")
                    header_text = first_header.text.strip()
                    current_first_date = datetime.strptime(header_text, "%A %d %B %Y").date()

                    if current_first_date >= target_start:
                        break

                    next_btn = driver.find_element(By.XPATH, "//span[@class='rbc-btn-group']/button[contains(text(), 'Next')]")
                    next_btn.click()
                    time.sleep(2)
                except Exception as e:
                    print(f"Navigation error: {e}")
                    break

            # 4. Extract Events from List View
            max_pages = 200 # Safety limit
            page_count = 0

            # (link, day) pairs already emitted. Pages overlap when the date
            # input and the "Next" fallback both move the calendar, and a
            # listing must not be emitted twice for the same day.
            seen_occurrences = set()

            while page_count < max_pages:
                page_count += 1
                print(f"Scraping Page {page_count}...")

                # Both row kinds, in document order — the loop below reads a
                # `.day-header` to set the current date and applies it to the
                # `.card-grid` rows that follow, so order is load-bearing.
                #
                # This used to be `.rbc-list-table > tbody > div`, which the SU
                # broke by swapping the list's real `<table>` for divs: the rows
                # now sit under an unclassed wrapper div instead of a `tbody`.
                # Nothing else moved — `.day-header` and `.card-grid` are
                # untouched — so a descendant match on the row classes says what
                # we actually mean and survives the next wrapper someone adds.
                rows = driver.find_elements(
                    By.CSS_SELECTOR,
                    ".rbc-list-content .rbc-list-table div.day-header, "
                    ".rbc-list-content .rbc-list-table div.card-grid",
                )

                current_date_obj = None
                last_event_date = None

                for row in rows:
                    try:
                        class_attr = row.get_attribute("class")

                        if "day-header" in class_attr:
                            header_text = row.text.strip()
                            try:
                                current_date_obj = datetime.strptime(header_text, "%A %d %B %Y").date()
                                last_event_date = current_date_obj
                            except Exception as e:
                                print(f"Failed to parse date header '{header_text}': {e}")
                            continue

                        if "card-grid" in class_attr:
                            if not current_date_obj:
                                continue

                            try:
                                link_el = row.find_element(By.TAG_NAME, "a")
                                link = link_el.get_attribute("href")
                            except:
                                continue

                            # One event per (link, day-header). A listing that
                            # reappears under a later day is a *recurring
                            # series*, not one long event. The old code
                            # extended the first occurrence's end_time to the
                            # later day's 23:59 while keeping day one's 00:00
                            # start — inventing a multi-day span and throwing
                            # away every date in the series but the first.
                            occurrence = (link, current_date_obj)
                            if occurrence in seen_occurrences:
                                continue

                            time_str = ""
                            title_str = ""
                            try:
                                title_container = row.find_element(By.CSS_SELECTOR, ".MuiListItemText-primary")
                                title_text_full = title_container.text
                                title_str = title_text_full
                                try:
                                    time_div = title_container.find_element(By.CSS_SELECTOR, ".list-item--time")
                                    time_str = time_div.text.strip()
                                    title_str = title_text_full.replace(time_str, "").strip()
                                except:
                                    pass
                                title_str = _clean_title(title_str)
                            except:
                                continue

                            seen_occurrences.add(occurrence)

                            start_dt, end_dt = _parse_time_range(time_str, current_date_obj)
                            time_known = start_dt is not None

                            location = ""
                            society = ""
                            try:
                                meta_container = row.find_element(By.CSS_SELECTOR, ".MuiListItemText-secondary")
                                try:
                                    loc_span = meta_container.find_element(By.CSS_SELECTOR, ".list-item--location span")
                                    location = loc_span.text.strip()
                                except: pass
                                try:
                                    group_span = meta_container.find_element(By.CSS_SELECTOR, ".list-item--group span")
                                    society = group_span.text.strip()
                                except: pass
                            except: pass

                            self.events.append({
                                "title": title_str,
                                "link": link,
                                # Per-day identity. The link alone stopped
                                # being unique the moment a series emitted one
                                # event per day, and AdhocEvent.sourceId is
                                # UNIQUE — consumers should key on this and
                                # fall back to `link` only for older payloads.
                                "source_id": f"{link}#{current_date_obj.isoformat()}",
                                "date": current_date_obj.isoformat(),
                                "start_time": start_dt.isoformat() if start_dt else None,
                                "end_time": end_dt.isoformat() if end_dt else None,
                                # False = the listing gave a date but no time.
                                # Consumers must not fill that gap with
                                # midnight; that is the whole point.
                                "time_known": time_known,
                                "location": location,
                                "host_name": society,
                                # Filled in by `enrich_event_details` from the
                                # listing's own page. Present-and-empty rather
                                # than absent so the key is always there, but
                                # see `parse_event_tags` on why empty is not
                                # the same claim as untagged.
                                "tags": [],
                                # Enrichment overwrites this if the event's own
                                # page yields a real description; otherwise this
                                # fallback is kept instead of an empty string.
                                "description": f"Organized by {society}. Location: {location}",
                            })

                    except Exception as row_e:
                        pass

                target_end_date = datetime.strptime(self.end_date, "%Y-%m-%d").date()
                if last_event_date and last_event_date >= target_end_date:
                    print(f"Reached target date {last_event_date}, stopping pagination.")
                    break

                # A page with no rows at all means the list is empty or we can no
                # longer read it. Either way there is nothing to page *towards*:
                # `last_event_date` stays None, so the check above can never fire
                # and the only remaining exit is the 200-page safety limit.
                #
                # That is exactly what the tbody change above caused — a run on
                # 2026-08-20 clicked "Next" 200 times over 10m45s, walking four
                # years into an empty future, and reported zero events scraped.
                # A break here turns the next such breakage into a fast, honest
                # zero instead of a ten-minute one.
                if not rows:
                    print("No rows on this page — stopping pagination.")
                    break

                # Pagination
                try:
                    toolbar_next = driver.find_element(By.XPATH, "//span[@class='rbc-btn-group']/button[contains(text(), 'Next')]")
                    if toolbar_next and toolbar_next.is_displayed():
                        toolbar_next.click()
                        time.sleep(3)
                    else:
                        break
                except:
                    break

            self.enrich_event_details(self.events)

        except Exception as e:
            print(f"Failed during scrape: {e}")
        finally:
            if driver:
                driver.quit()

        return {"events": self.events}
