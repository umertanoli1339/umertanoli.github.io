import csv
import re
from typing import List, Dict
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://doctor.webmd.com/results?entity=all&q=&pagenumber=1&pt=29.3838,-94.9027&d=40&city=Texas%20City&state=TX"
API_BASE = "https://www.webmd.com/kapi/secure/search/care/allresults"


def build_params(page_number: int) -> Dict[str, str]:
    return {
        "sortby": "bestmatch",
        "entity": "all",
        "gender": "all",
        "distance": "40",
        "newpatient": "",
        "isvirtualvisit": "",
        "minrating": "0",
        "start": str((page_number - 1) * 10),
        "pagename": "serp",
        "q": "",
        "pt": "29.3838,-94.9027",
        "specialtyid": "",
        "d": "40",
        "sid": "",
        "pid": "",
        "insuranceid": "",
        "exp_min": "min",
        "exp_max": "max",
        "state": "TX",
        "amagender": "all",
    }


def scrape(pages: int = 3, delay_ms: int = 800) -> List[List[str]]:
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
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')", "button:has-text('I Agree')"]:
            try:
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    break
            except Exception:
                pass

        for pg in range(1, pages + 1):
            params = build_params(pg)
            api_url = API_BASE + "?" + urlencode(params)
            # Build headers explicitly
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
            hdrs = {
                "referer": "https://doctor.webmd.com/",
                "accept": "application/json, text/plain, */*",
                "user-agent": ua,
                "sec-ch-ua": '"Not;A=Brand";v="99", "HeadlessChrome";v="139", "Chromium";v="139"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
            # Try up to 3 times in case header gating blocks the first call
            resp = None
            for attempt in range(3):
                resp = context.request.get(api_url, headers=hdrs)
                if resp.status == 200:
                    break
                page.wait_for_timeout(500)
            if not resp or resp.status != 200:
                print(f"[WARN] API {api_url} returned {resp.status if resp else 'none'}")
                continue
            data = resp.json()
            items = data.get("data", {}).get("response", [])
            for it in items:
                firstname = it.get("firstname", "")
                lastname = it.get("lastname", "")
                name = (firstname + " " + lastname).strip()
                npi = it.get("npi", "")
                business = it.get("primaryspecialty_nis", "")
                phone = it.get("phoneno") or it.get("phone") or ""
                address = it.get("address") or ""
                city = it.get("city") or ""
                state = it.get("state") or ""
                zip_code = it.get("zip") or ""
                location = ", ".join([x for x in [address, city, state, zip_code] if x])
                profile_slug = it.get("urlseo") or it.get("url") or ""
                if profile_slug and profile_slug.startswith("/"):
                    profile_url = "https://doctor.webmd.com" + profile_slug
                elif profile_slug and profile_slug.startswith("http"):
                    profile_url = profile_slug
                else:
                    profile_url = ""

                rows.append([
                    name,
                    business,
                    "",  # email unknown
                    phone,
                    location,
                    profile_url,
                ])
            page.wait_for_timeout(delay_ms)

        context.close()
        browser.close()
    return rows


if __name__ == "__main__":
    out = "webmd_full_data_playwright_api.csv"
    rows = scrape(pages=3, delay_ms=800)
    headers = ["Name", "Business Name", "Email", "WhatsApp/Phone", "Location", "Profile URL"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"Saved {len(rows)} rows to {out}")