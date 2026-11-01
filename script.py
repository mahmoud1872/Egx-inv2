
import os
import time
import json
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

URL = "https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx"

PAGE_WAIT_SECONDS = 15000
REQUEST_TIMEOUT = 90000
MAX_BODY_LENGTH = 200000

def save_file(filename, content):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)


def fetch_html():
    xhr_log = []
    html = None

    def on_response(response):
        try:
            request = response.request
            resource_type = request.resource_type
            content_type = response.headers.get(
                "content-type", ""
            )

            if (
                resource_type in ("xhr", "fetch")
                or any(
                    item in content_type.lower()
                    for item in ("json", "xml")
                )
                or ".ashx" in response.url.lower()
                or ".asmx" in response.url.lower()
            ):
                try:
                    body = response.text()
                except Exception as e:
                    body = f"Could not read response: {e}"

                xhr_log.append(
                    "\n" + "=" * 100 + "\n"
                    f"TIME: {datetime.now().isoformat()}\n"
                    f"STATUS: {response.status}\n"
                    f"RESOURCE TYPE: {resource_type}\n"
                    f"CONTENT TYPE: {content_type}\n"
                    f"METHOD: {request.method}\n"
                    f"URL: {response.url}\n"
                    f"POST DATA: {request.post_data or ''}\n"
                    f"BODY:\n{body[:MAX_BODY_LENGTH]}\n"
                )

        except Exception as e:
            print(f"Response capture error: {e}")

    try:
        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="ar-EG",
                timezone_id="Africa/Cairo",
                viewport={
                    "width": 1366,
                    "height": 900
                }
            )

            page = context.new_page()

            page.on("response", on_response)

            print("Opening EGX page...")

            try:
                response = page.goto(
                    URL,
                    timeout=REQUEST_TIMEOUT,
                    wait_until="domcontentloaded"
                )

                if response:
                    print(
                        f"Page HTTP status: {response.status}"
                    )

                print("Waiting for dynamic content...")
                page.wait_for_timeout(PAGE_WAIT_SECONDS)

                html = page.content()

                save_file("page.html", html)

                page.screenshot(
                    path="page.png",
                    full_page=True
                )

                # Save visible page text
                visible_text = page.locator("body").inner_text()

                save_file(
                    "page_text.txt",
                    visible_text
                )

                print(
                    f"HTML captured: {len(html)} characters"
                )

            except Exception as e:
                print(f"Page loading error: {e}")
                save_file("error.txt", str(e))

            browser.close()

    except Exception as e:
        print(f"Playwright error: {e}")
        save_file("error.txt", str(e))

    save_file(
        "xhr_log.txt",
        "\n".join(xhr_log)
        if xhr_log
        else "No XHR/FETCH responses captured."
    )

    print(
        f"Captured {len(xhr_log)} network responses."
    )

    return html


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Missing Telegram credentials.")
        return

    api_url = (
        f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            api_url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print(
            f"Telegram status: {response.status_code}"
        )

        if not response.ok:
            print(response.text)

    except Exception as e:
        print(f"Telegram error: {e}")


def main():
    print("=" * 60)
    print("EGX INVESTOR DATA DIAGNOSTIC")
    print(datetime.now().isoformat())
    print("=" * 60)

    html = fetch_html()

    if not html:
        print("No HTML received.")

        send_telegram(
            "EGX scraper: Failed to retrieve the page. "
            "Check GitHub Actions artifacts."
        )
        return

    print("Page retrieved successfully.")

    send_telegram(
        "EGX diagnostic scraper completed.\n"
        "Network responses have been captured.\n"
        "Download the debug artifact from GitHub Actions "
        "to inspect the investor data source."
    )


if __name__ == "__main__":
    main()
