import csv
import re
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlparse, parse_qs
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_RESULTS = "https://doctor.webmd.com/results"


def build_results_url(page_number: int) -> str:
    params = {
        "entity": "all",
        "q": "",
        "pagenumber": str(page_number),
        "pt": "29.3838,-94.9027",
        "d": "40",
        "city": "Texas City",
        "state": "TX",
    }
    return BASE_RESULTS + "?" + urlencode(params)


def extract_email_from_text(text: str) -> str:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")
    return match.group(0) if match else ""


def fetch_email_from_external(browser, url: str, timeout_ms: int = 30000) -> str:
    if not url:
        return ""
    try:
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        pg.wait_for_timeout(2000)
        html = pg.content()
        ctx.close()
        return extract_email_from_text(html)
    except Exception:
        return ""


def parse_profile(page, browser, url: str) -> Dict[str, str]:
    data = {"phone": "", "location": "", "email": ""}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector("h1", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        # Phone
        try:
            tel = page.locator("a[href^='tel:']").first
            if tel and tel.count():
                data["phone"] = tel.inner_text().strip()
        except Exception:
            pass
        # Location
        for sel in [".adr", "address", "[itemprop='address']"]:
            loc = page.locator(sel)
            if loc.count():
                data["location"] = re.sub(r"\s+", " ", loc.first.inner_text()).strip()
                break
        # Website -> email
        website_link = ""
        for sel in ["a:has-text('Website')", "a:has-text('Visit Website')", "a:has-text('website')"]:
            link = page.locator(sel)
            if link.count():
                website_link = link.first.get_attribute("href") or ""
                break
        if website_link:
            data["email"] = fetch_email_from_external(browser, website_link)
    except Exception:
        pass
    return data


def scrape(pages: int = 3, delay_ms: int = 800, per_page_wait_ms: int = 8000) -> List[List[str]]:
    rows: List[List[str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            geolocation={"latitude": 29.3838, "longitude": -94.9027},
            permissions=["geolocation"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Capture API JSON from SPA calls
        store: Dict[str, Optional[dict]] = {"data": None}

        def on_response(res):
            if "kapi/secure/search/care/allresults" in res.url and res.status == 200:
                try:
                    store["data"] = res.json()
                except Exception:
                    try:
                        import json as _json
                        store["data"] = _json.loads(res.text())
                    except Exception:
                        pass

        page.on("response", on_response)

        accepted_cookies = False

        for pg_num in range(1, pages + 1):
            store["data"] = None
            url = build_results_url(pg_num)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            if not accepted_cookies:
                for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')", "button:has-text('I Agree')"]:
                    try:
                        btn = page.locator(sel)
                        if btn.count():
                            btn.first.click(timeout=3000)
                            page.wait_for_timeout(500)
                            accepted_cookies = True
                            break
                    except Exception:
                        pass

            # Give the SPA time to fire the API request
            page.wait_for_timeout(per_page_wait_ms)

            # Fallback: small scroll to stimulate lazy loads
            if store["data"] is None:
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                page.wait_for_timeout(2000)

            data = store["data"] or {"data": {"response": []}}
            items = data.get("data", {}).get("response", [])
            if not items:
                print(f"[WARN] No API data captured for page {pg_num}")

            for it in items:
                firstname = it.get("firstname", "")
                lastname = it.get("lastname", "")
                name = (firstname + " " + lastname).strip()
                business = it.get("primaryspecialty_nis", "")
                profile_slug = it.get("urlseo") or it.get("url") or ""
                if profile_slug and profile_slug.startswith("/"):
                    profile_url = "https://doctor.webmd.com" + profile_slug
                elif profile_slug and profile_slug.startswith("http"):
                    profile_url = profile_slug
                else:
                    profile_url = ""

                phone = ""
                location = ""
                email = ""
                if profile_url:
                    prof = parse_profile(page, browser, profile_url)
                    phone = prof.get("phone", "")
                    location = prof.get("location", "")
                    email = prof.get("email", "")

                rows.append([name, business, email, phone, location, profile_url])
                page.wait_for_timeout(delay_ms)

        context.close()
        browser.close()

    return rows


if __name__ == "__main__":
    out = "webmd_full_data_playwright.csv"
    rows = scrape(pages=3, delay_ms=400, per_page_wait_ms=8000)
    headers = ["Name", "Business Name", "Email", "WhatsApp/Phone", "Location", "Profile URL"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {out}")