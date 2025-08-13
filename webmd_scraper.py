import re
import csv
from typing import List, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


def get_email_from_website(browser, url: str) -> str:
    if not url:
        return ""
    try:
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        page_content = page.content()
        context.close()
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", page_content)
        return match.group(0) if match else ""
    except Exception:
        return ""


def parse_doctor_profile(page, browser, profile_url: str) -> Tuple[str, str, str, str, str]:
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("h1", timeout=20000)

        name = clean_text(page.locator("h1").first.inner_text()) if page.locator("h1").count() else ""

        business = ""
        for selector in [".prov-specialty", ".provider-specialties", "[data-qa='provider-specialties']"]:
            locator = page.locator(selector)
            if locator.count():
                business = clean_text(locator.first.inner_text())
                break

        location = ""
        for selector in [".adr", "address", "[itemprop='address']"]:
            locator = page.locator(selector)
            if locator.count():
                location = clean_text(locator.first.inner_text())
                break

        phone = ""
        for selector in [".prov-phone", "a[href^='tel:']", "[data-qa='provider-phone']"]:
            locator = page.locator(selector)
            if locator.count():
                phone = clean_text(locator.first.inner_text())
                break

        email = ""
        try:
            website_link = ""
            link_locator = page.get_by_role("link", name=re.compile("Website", re.I))
            if link_locator.count():
                website_link = link_locator.first.get_attribute("href") or ""
            if not website_link:
                link_locator = page.locator("a:has-text('Website')")
                if link_locator.count():
                    website_link = link_locator.first.get_attribute("href") or ""
            if website_link:
                email = get_email_from_website(browser, website_link)
        except Exception:
            email = ""

        return name, business, email, phone, location
    except Exception as e:
        print(f"[ERROR] Failed to parse {profile_url}: {e}")
        return "", "", "", "", ""


def parse_results_page(page, url: str) -> List[str]:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    for attempt in range(3):
        try:
            page.wait_for_selector(".provider-details", timeout=20000)
            break
        except PlaywrightTimeoutError:
            if attempt == 2:
                break
            print(f"[WARN] Page load delayed, retrying... ({attempt + 1}/3)")
            page.wait_for_timeout(3000)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

    profile_links: List[str] = []

    def harvest_links(selector: str) -> None:
        try:
            hrefs = page.locator(selector).evaluate_all("els => els.map(e => e.getAttribute('href'))")
            for href in hrefs:
                if href and "/doctor/" in href and href not in profile_links:
                    profile_links.append(href)
        except Exception:
            pass

    harvest_links(".provider-details a[href*='/doctor/']")
    harvest_links("a[href*='/doctor/']")

    return profile_links


def scrape_webmd(base_url: str, pages: int = 1, delay: float = 2.0):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        all_rows = []
        try:
            for page_number in range(1, pages + 1):
                paged_url = re.sub(r"pagenumber=\d+", f"pagenumber={page_number}", base_url)
                print(f"Scraping results page {page_number}...")

                profile_urls = parse_results_page(page, paged_url)

                for profile in profile_urls:
                    print(f"   -> Visiting profile: {profile}")
                    name, business, email, phone, location = parse_doctor_profile(page, browser, profile)
                    all_rows.append([
                        name,
                        business,
                        email,
                        phone,
                        location,
                        profile,
                    ])
                    page.wait_for_timeout(1000)

                page.wait_for_timeout(int(delay * 1000))
        finally:
            context.close()
            browser.close()

        return all_rows


if __name__ == "__main__":
    target_url = (
        "https://doctor.webmd.com/results?entity=all&q=&pagenumber=1&pt=29.3838,-94.9027&d=40&city=Texas%20City&state=TX"
    )
    rows = scrape_webmd(target_url, pages=3, delay=2)
    output_csv = "webmd_full_data_playwright.csv"
    headers = ["Name", "Business Name", "Email", "WhatsApp/Phone", "Location", "Profile URL"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Scraping complete! {len(rows)} doctors saved to '{output_csv}'")