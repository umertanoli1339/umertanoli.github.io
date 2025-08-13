from playwright.sync_api import sync_playwright
import re

URL = "https://doctor.webmd.com/results?entity=all&q=&pagenumber=1&pt=29.3838,-94.9027&d=40&city=Texas%20City&state=TX"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    # Try accept cookies if present
    for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')", "button:has-text('I Agree')"]:
        try:
            btn = page.locator(sel)
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    # Give time for JS to render
    page.wait_for_timeout(5000)

    # Measure multiple selectors
    num_doc_links = page.locator("a[href*='/doctor/']").count()
    num_results_cards = page.locator(".results-card").count()
    num_provider_details = page.locator(".provider-details").count()

    print("/doctor/ links:", num_doc_links)
    print(".results-card:", num_results_cards)
    print(".provider-details:", num_provider_details)

    # Print first 10 hrefs
    hrefs = page.locator("a[href*='/doctor/']").evaluate_all("els => els.slice(0,10).map(e => e.href)")
    print("sample hrefs:")
    for h in hrefs:
        print(" ", h)

    context.close()
    browser.close()