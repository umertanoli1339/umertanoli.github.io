from playwright.sync_api import sync_playwright
import json

URL = "https://doctor.webmd.com/results?entity=all&q=&pagenumber=1&pt=29.3838,-94.9027&d=40&city=Texas%20City&state=TX"

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

    def on_response(response):
        url = response.url
        if "kapi/secure/search/care/allresults" in url:
            try:
                print("RES:", response.status, url)
                req = response.request
                print("REQ headers:")
                for k, v in req.headers.items():
                    if k.lower() in {"cookie", "authorization"}:
                        continue
                    print(f"  {k}: {v}")
                ct = response.headers.get("content-type", "")
                if "application/json" in ct:
                    data = response.json()
                else:
                    data = json.loads(response.text())
                print("JSON keys:", list(data.keys()))
                items = data.get("data", {}).get("response", [])
                print("items count:", len(items))
                if items:
                    first = items[0]
                    sample = {k: first.get(k) for k in [
                        "providerid", "firstname", "lastname", "npi", "url", "urlseo",
                        "city", "state", "zip", "phoneno", "primaryspecialty_nis"
                    ]}
                    print("sample:", sample)
            except Exception as e:
                print("ERR parsing response:", e)

    page.on("response", on_response)

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')", "button:has-text('I Agree')"]:
        try:
            btn = page.locator(sel)
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    page.wait_for_timeout(8000)

    context.close()
    browser.close()