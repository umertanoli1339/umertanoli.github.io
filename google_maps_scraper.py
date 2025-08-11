import time
import random
import re
import datetime
from typing import List, Tuple, Optional, Dict

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ---------- CONFIG ----------
HEADLESS = False
MAX_RESULTS = 50  # Reduced for testing
WAIT_TIMEOUT = 30
OUTPUT_DIR = "/workspace"
SCROLL_PAUSE_TIME = 1.25
RETRY_LIMIT = 3
# ----------------------------


def clean_text(s: Optional[str]) -> str:
    if not s or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s)
    s = re.sub(r"[\uE000-\uF8FF]", "", s)  # Remove emojis (PUA)
    s = re.sub(r"[\x00-\x1F\x7F]", " ", s)  # Remove control chars
    s = re.sub(r"\s+", " ", s).strip()
    return s


phone_rx = re.compile(r"(\+?\d[\d\-\s\(\)]{8,}\d)")
email_rx = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_phone(text: Optional[str]) -> str:
    if not text:
        return ""
    m = phone_rx.search(text)
    return m.group(1).strip() if m else ""


def extract_email(text: Optional[str]) -> str:
    if not text:
        return ""
    m = email_rx.search(text)
    return m.group(0).lower() if m else ""


def setup_driver() -> webdriver.Chrome:
    options = Options()
    if HEADLESS:
        options.add_argument("--headless=new")

    # Stability/perf
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    # Stealth-ish
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    driver.implicitly_wait(5)
    return driver


def handle_consent_popup(driver: webdriver.Chrome) -> None:
    # Google sometimes shows a consent dialog inside an iframe
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='consent']")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                btns = driver.find_elements(By.XPATH, "//button[.//span[contains(., 'I agree')] or contains(., 'I agree') or contains(., 'Accept all')]")
                if not btns:
                    btns = driver.find_elements(By.XPATH, "//button[contains(., 'Agree') or contains(., 'Accept')]")
                if btns:
                    btns[0].click()
                    time.sleep(1)
                    print("[INFO] Accepted consent popup (iframe).")
                    driver.switch_to.default_content()
                    return
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
                continue
    except Exception:
        pass

    # Fallback: top-level dialog
    try:
        consent_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'I agree') or contains(., 'Accept all') or contains(., 'Agree') or contains(., 'Accept')]")
            )
        )
        consent_btn.click()
        print("[INFO] Accepted consent popup.")
        time.sleep(1)
    except Exception:
        print("[INFO] No consent popup found.")


def _find_results_feed(driver: webdriver.Chrome):
    feeds = driver.find_elements(By.CSS_SELECTOR, "div[role='feed']")
    return feeds[0] if feeds else None


def scroll_results_to_bottom(driver: webdriver.Chrome, max_scrolls: int = 50) -> None:
    feed = _find_results_feed(driver)
    if not feed:
        # As a fallback, try window scroll (less reliable)
        print("[INFO] Results feed not found; falling back to window scroll.")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(max_scrolls):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE_TIME)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        return

    last_scroll_top = -1
    same_count = 0
    for _ in range(max_scrolls):
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", feed)
        time.sleep(SCROLL_PAUSE_TIME)
        scroll_top = driver.execute_script("return arguments[0].scrollTop;", feed)
        if scroll_top == last_scroll_top:
            same_count += 1
            if same_count >= 3:
                break
        else:
            same_count = 0
        last_scroll_top = scroll_top


def get_listings(driver: webdriver.Chrome) -> List:
    """Get all listing elements with robust selectors scoped to the results feed."""
    selectors = [
        "div[role='feed'] div.Nv2PK",  # primary listing container
        "div[role='feed'] div[aria-label][jsaction]",  # generic result items
        "div.Nv2PK",  # fallback
        "div[role='article']",  # legacy
    ]

    for attempt in range(RETRY_LIMIT):
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                elements = [el for el in elements if el.is_displayed()]
                if elements:
                    print(f"[INFO] Found {len(elements)} listings with selector: {selector}")
                    return elements
            except Exception as e:
                print(f"[WARNING] Selector {selector} failed: {str(e)}")
        print(f"[INFO] No listings found, attempt {attempt + 1}/{RETRY_LIMIT}")
        time.sleep(1.5)
        scroll_results_to_bottom(driver, max_scrolls=5)

    return []


def _first_text(driver: webdriver.Chrome, selectors: List[Tuple[str, str]]) -> str:
    for by, sel in selectors:
        try:
            el = driver.find_element(by, sel)
            txt = clean_text(el.text)
            if txt:
                return txt
        except Exception:
            continue
    return ""


def scrape_business_details(driver: webdriver.Chrome) -> Dict[str, str]:
    """Scrape details from the business panel with robust error handling"""
    details: Dict[str, str] = {
        "Business Name": "",
        "Phone Number": "",
        "Website": "",
        "Address": "",
        "Rating": "",
        "Reviews": "",
        "Email": "",
    }

    try:
        # Business Name
        details["Business Name"] = _first_text(
            driver,
            [
                (By.CSS_SELECTOR, "div[role='main'] h1.DUwDvf"),
                (By.CSS_SELECTOR, "div[role='main'] h1[aria-level='1']"),
                (By.CSS_SELECTOR, "div[role='main'] h1"),
            ],
        )

        # Phone Number
        try:
            phone_candidates = driver.find_elements(By.CSS_SELECTOR, "button[data-item-id^='phone'], a[href^='tel:']")
            phone_text = ""
            for el in phone_candidates:
                phone_text = el.get_attribute("aria-label") or el.text or el.get_attribute("href") or ""
                phone_text = clean_text(phone_text)
                phone = extract_phone(phone_text)
                if phone:
                    details["Phone Number"] = phone
                    break
        except Exception:
            pass

        # Website
        try:
            site_candidates = driver.find_elements(
                By.CSS_SELECTOR,
                "a[aria-label*='Website'], a[data-item-id='authority'], a[href^='http']:not([aria-label*='Directions'])",
            )
            for el in site_candidates:
                href = el.get_attribute("href") or ""
                if href and "google.com" not in href:
                    details["Website"] = clean_text(href)
                    break
        except Exception:
            pass

        # Address
        try:
            addr_candidates = driver.find_elements(By.CSS_SELECTOR, "button[data-item-id^='address'], button[aria-label*='Address']")
            for el in addr_candidates:
                addr_text = el.get_attribute("aria-label") or el.text
                addr_text = clean_text(addr_text)
                if addr_text:
                    details["Address"] = addr_text
                    break
        except Exception:
            pass

        # Rating and Reviews
        try:
            # Rating typically in aria-label like "4.6 stars"
            rating_span = None
            spans = driver.find_elements(By.CSS_SELECTOR, "div[role='main'] span[aria-label*='stars']")
            if spans:
                rating_span = spans[0]
            if rating_span:
                aria = rating_span.get_attribute("aria-label") or ""
                m = re.search(r"([0-9]+\.[0-9]+|[0-9]+)\s+stars", aria)
                if m:
                    details["Rating"] = m.group(1)

            # Reviews often on a button containing "reviews"
            review_btns = driver.find_elements(By.CSS_SELECTOR, "div[role='main'] button[aria-label*='reviews'], div[role='main'] button:has(span[aria-label*='reviews'])")
            reviews_text = ""
            for btn in review_btns:
                txt = clean_text(btn.text)
                if txt and ("review" in txt.lower() or re.search(r"\b\d+[\,\.]?\d*\b", txt)):
                    reviews_text = txt
                    break
            if reviews_text:
                m2 = re.search(r"([0-9][0-9,\.]*)", reviews_text)
                if m2:
                    details["Reviews"] = m2.group(1).replace(",", "")
        except Exception:
            pass

        # Email (best effort; rarely present directly in Maps)
        details["Email"] = clean_text(extract_email(driver.page_source))

    except Exception as e:
        print(f"[WARNING] Error scraping details: {str(e)}")

    return details


def click_listing(driver: webdriver.Chrome, listing) -> None:
    # Prefer clicking the internal anchor if present
    try:
        link = listing.find_element(By.CSS_SELECTOR, "a.hfPXJ, a[href^='https://www.google.com/maps/place']")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
        time.sleep(random.uniform(0.2, 0.6))
        driver.execute_script("arguments[0].click();", link)
        return
    except Exception:
        pass

    # Fallback: click the whole listing
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", listing)
    time.sleep(random.uniform(0.2, 0.6))
    driver.execute_script("arguments[0].click();", listing)


def wait_for_place_panel(driver: webdriver.Chrome) -> None:
    # Ensure the main panel title exists
    WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='main'] h1"))
    )


def scrape_map_search(url_or_query: str) -> Optional[str]:
    driver = setup_driver()
    results: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    try:
        # Build the URL
        url = (
            url_or_query
            if url_or_query.startswith("http")
            else f"https://www.google.com/maps/search/{url_or_query.replace(' ', '+')}"
        )
        print(f"[INFO] Loading URL: {url}")

        driver.get(url)
        handle_consent_popup(driver)

        # If single place page
        if "/place/" in driver.current_url:
            wait_for_place_panel(driver)
            details = scrape_business_details(driver)
            if details["Business Name"] or details["Address"]:
                results.append(details)
        else:
            # Wait for results feed
            WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='feed'], div[aria-label*='results']"))
            )

            # Scroll the results pane to load more
            scroll_results_to_bottom(driver)

            # Get all listings
            listings = get_listings(driver)
            if not listings:
                print("[ERROR] No listings found after multiple attempts")
                return None

            # Process each listing
            for i, listing in enumerate(listings[:MAX_RESULTS]):
                retry_count = 0
                while retry_count < RETRY_LIMIT:
                    try:
                        click_listing(driver, listing)
                        time.sleep(random.uniform(0.8, 1.6))

                        wait_for_place_panel(driver)
                        details = scrape_business_details(driver)

                        key = (
                            clean_text(details["Business Name"]).lower(),
                            clean_text(details["Address"]).lower(),
                        )
                        if key not in seen and any(key):
                            seen.add(key)
                            results.append(details)
                            print(f"[COLLECTED] {len(results)}: {details['Business Name']}")

                        break  # success for this listing
                    except Exception as e:
                        retry_count += 1
                        print(f"[WARNING] Attempt {retry_count}/{RETRY_LIMIT} failed for listing {i}: {str(e)}")
                        time.sleep(1.5)
                        # Refresh listing reference in case DOM changed
                        fresh = get_listings(driver)
                        if i < len(fresh):
                            listing = fresh[i]
                        else:
                            break

        # Save results
        if results:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{OUTPUT_DIR}/google_maps_results_{ts}.csv"
            pd.DataFrame(results).to_csv(output_file, index=False, encoding="utf-8-sig")
            print(f"[DONE] Saved {len(results)} records to: {output_file}")
            return output_file
        else:
            print("[WARNING] No results collected.")
            return None

    except Exception as e:
        print(f"[ERROR] Main scraping error: {str(e)}")
        return None

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    import sys

    query = "restaurants in Dubai DIFC" if len(sys.argv) < 2 else " ".join(sys.argv[1:])
    print(f"[START] Scraping: {query}")
    result = scrape_map_search(query)
    if not result:
        print(
            "[ERROR] Scraping failed completely. Try again with a different query or check the selectors."
        )