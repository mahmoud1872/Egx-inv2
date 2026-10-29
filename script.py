import io
import os
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
URL = "https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx"

TOTAL_RUNS = 13
INTERVAL_SECONDS = 1200  # 20 minutes

# (keyword to look for, name shown in the message) - keywords are normalized
TARGETS = [
    ("الافراد", "الافراد حسب الجنسيه"),
    ("المؤسسات", "المؤسسات حسب الجنسيه"),
]


def normalize(text):
    """Make Arabic spelling variants comparable (أ/إ/آ -> ا, ة -> ه, ى -> ي)."""
    text = str(text)
    text = re.sub("[أإآ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")
    return text


def fetch_html():
    """Open the page in a headless browser. Saves debug files every run."""
    xhr_log = []

    def on_response(resp):
        try:
            ctype = resp.headers.get("content-type", "")
            if any(t in ctype for t in ("json", "xml", "javascript")) or "ashx" in resp.url:
                body = ""
                try:
                    body = resp.text()[:2000]
                except Exception:
                    pass
                xhr_log.append(f"{resp.status} {ctype}\n{resp.url}\n{body}\n{'-' * 60}")
        except Exception:
            pass

    html = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="ar-EG",
                timezone_id="Africa/Cairo",
                viewport={"width": 1366, "height": 900},
            )
            page = context.new_page()
            page.on("response", on_response)
            try:
                page.goto(URL, timeout=90000, wait_until="domcontentloaded")
                page.wait_for_timeout(10000)  # let dynamic content render
            except Exception as e:
                print(f"Page load problem: {e}")
                with open("error.txt", "w", encoding="utf-8") as f:
                    f.write(str(e))

            # Debug files (uploaded as artifacts by the workflow)
            try:
                page.screenshot(path="page.png", full_page=True)
            except Exception as e:
                print(f"Screenshot failed: {e}")
            try:
                html = page.content()
                with open("page.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception as e:
                print(f"Could not read page content: {e}")
            browser.close()
    except Exception as e:
        print(f"Playwright error: {e}")
        with open("error.txt", "w", encoding="utf-8") as f:
            f.write(str(e))

    with open("xhr_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(xhr_log) if xhr_log else "No JSON/XML responses captured")

    return html


def parse_tables(html):
    extracted = {}

    # 1. pandas read_html
    try:
        dfs = pd.read_html(io.StringIO(html))
        print(f"pandas parsed {len(dfs)} tables.")
        for df in dfs:
            df_str = normalize(df.to_string())
            for keyword, target_name in TARGETS:
                if normalize(keyword) in df_str and target_name not in extracted:
                    records = []
                    for _, row in df.iterrows():
                        vals = [str(v).strip() for v in row.values if pd.notna(v)]
                        if len(vals) >= 2:
                            records.append({"name": vals[0], "value": vals[-1]})
                    if records:
                        extracted[target_name] = records
    except Exception as e:
        print(f"pandas read_html warning: {e}")

    # 2. BeautifulSoup fallback
    if len(extracted) < len(TARGETS):
        print("Running BeautifulSoup fallback...")
        soup = BeautifulSoup(html, "html.parser")
        for keyword, target_name in TARGETS:
            if target_name in extracted:
                continue
            kw = normalize(keyword)
            heading = soup.find(
                lambda tag: tag.name in ["div", "span", "h2", "h3", "h4", "th", "td"]
                and tag.get_text()
                and kw in normalize(tag.get_text())
            )
            if heading:
                table = heading.find_parent("table") or heading.find_next("table")
                if table:
                    records = []
                    for tr in table.find_all("tr"):
                        cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                        if len(cols) >= 2:
                            records.append({"name": cols[0], "value": cols[-1]})
                    if records:
                        extracted[target_name] = records

    return extracted


def get_data():
    print("Launching headless browser to fetch EGX page...")
    html = fetch_html()
    if not html:
        print("No HTML received (site unreachable or blocked?).")
        return None

    print(f"Received {len(html)} characters of HTML.")
    data = parse_tables(html)

    if not data:
        print("--- DIAGNOSTIC: page text snippet ---")
        print(BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:800])
        return None
    return data


def send(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram credentials (TOKEN or CHAT_ID) are missing!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)
        if not response.ok:
            print(f"Failed to send Telegram message: {response.text}")
        else:
            print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Telegram request failed: {e}")


if __name__ == "__main__":
    failure_notified = False

    for run_idx in range(TOTAL_RUNS):
        print(f"\n--- Run {run_idx + 1} of {TOTAL_RUNS} ---")
        data = get_data()

        if data:
            lines = []
            for section, records in data.items():
                lines.append(f"=== {section} ===")
                for rec in records:
                    lines.append(f"- {rec['name']}: {rec['value']}")
                lines.append("")
            message = "\n".join(lines)
            print(message)
            send(message)
        else:
            print("No matching data found.")
            # Only notify once per job so Telegram isn't spammed
            if not failure_notified:
                send("No data found or failed to scrape EGX website. Check the Actions log.")
                failure_notified = True

        if run_idx < TOTAL_RUNS - 1:
            print("Waiting 20 minutes for the next update...")
            time.sleep(INTERVAL_SECONDS)
