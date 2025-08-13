import csv
import re
import time
from typing import List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE = "https://doctor.webmd.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


def get(url: str, session: requests.Session, max_retries: int = 3, delay: float = 2.0) -> requests.Response:
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp
            # Retry on transient errors
            if resp.status_code in {429, 500, 502, 503, 504}:
                time.sleep(delay * attempt)
                continue
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay * attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed without exception")


def get_email_from_website(url: str, session: requests.Session) -> str:
    if not url:
        return ""
    try:
        resp = get(url, session)
        page_source = resp.text
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", page_source)
        return match.group(0) if match else ""
    except Exception:
        return ""


def parse_doctor_profile(profile_url: str, session: requests.Session) -> Tuple[str, str, str, str, str]:
    try:
        resp = get(profile_url, session)
        soup = BeautifulSoup(resp.text, "html.parser")

        name = clean_text(soup.find("h1").get_text()) if soup.find("h1") else ""

        business = ""
        for selector in [".prov-specialty", ".provider-specialties", "[data-qa='provider-specialties']"]:
            node = soup.select_one(selector)
            if node:
                business = clean_text(node.get_text())
                break

        location = ""
        for selector in [".adr", "address", "[itemprop='address']"]:
            node = soup.select_one(selector)
            if node:
                location = clean_text(node.get_text())
                break

        phone = ""
        for selector in [".prov-phone", "a[href^='tel:']", "[data-qa='provider-phone']"]:
            node = soup.select_one(selector)
            if node:
                phone = clean_text(node.get_text())
                break

        email = ""
        website_link = ""
        # Try anchors that contain the text 'Website'
        link = soup.find("a", string=re.compile("website", re.I))
        if link and link.get("href"):
            website_link = link.get("href")
        if website_link:
            website_link = urljoin(profile_url, website_link)
            email = get_email_from_website(website_link, session)

        return name, business, email, phone, location
    except Exception as e:
        print(f"[ERROR] Failed to parse {profile_url}: {e}")
        return "", "", "", "", ""


def parse_results_page(url: str, session: requests.Session) -> List[str]:
    resp = get(url, session)
    soup = BeautifulSoup(resp.text, "html.parser")

    profile_links: List[str] = []

    # Prefer links inside provider cards if present
    for selector in [
        ".provider-details a[href*='/doctor/']",
        "a[href*='/doctor/']",
    ]:
        for a in soup.select(selector):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(BASE, href)
            if "/doctor/" in full and full not in profile_links:
                profile_links.append(full)

    return profile_links


def scrape_webmd(base_url: str, pages: int = 1, delay: float = 2.0) -> List[List[str]]:
    session = requests.Session()
    rows: List[List[str]] = []

    for page_number in range(1, pages + 1):
        paged_url = re.sub(r"pagenumber=\d+", f"pagenumber={page_number}", base_url)
        print(f"Scraping results page {page_number}...")

        profile_urls = parse_results_page(paged_url, session)

        for profile in profile_urls:
            print(f"   -> Visiting profile: {profile}")
            name, business, email, phone, location = parse_doctor_profile(profile, session)
            rows.append([
                name,
                business,
                email,
                phone,
                location,
                profile,
            ])
            time.sleep(1)

        time.sleep(delay)

    return rows


if __name__ == "__main__":
    target_url = "https://doctor.webmd.com/results?entity=all&q=&pagenumber=1&pt=29.3838,-94.9027&d=40&city=Texas%20City&state=TX"
    rows = scrape_webmd(target_url, pages=3, delay=2)
    output_csv = "webmd_full_data_requests.csv"
    headers = ["Name", "Business Name", "Email", "WhatsApp/Phone", "Location", "Profile URL"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Scraping complete! {len(rows)} doctors saved to '{output_csv}'")