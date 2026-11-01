
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURATION
# ==========================================

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SIGMA_URL = (
    "https://www.sigma-cap.com/main/"
    "x_market_page_ar.overview?u_sess="
)

EGX_URL = (
    "https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx"
)

TOTAL_RUNS = 5
INTERVAL_SECONDS = 60
PAGE_WAIT_SECONDS = 8000

TIMEZONE = ZoneInfo("Africa/Cairo")

INVESTORS = [
    ("مصريين أفراد", 0),
    ("مصريين مؤسسات", 1),
    ("عرب أفراد", 2),
    ("عرب مؤسسات", 3),
    ("أجانب أفراد", 4),
    ("أجانب مؤسسات", 5),
]


def log(message):
    print(
        f"[{datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{message}",
        flush=True
    )


def save_file(filename, content):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)


def normalize(text):
    text = str(text)

    translation = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩٫٬−",
        "0123456789,,-"
    )

    text = text.translate(translation)
    text = re.sub(r"[أإآ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")

    return text.strip()


def parse_number(value):
    """
    Convert a cell containing a number into float.
    Supports Arabic and English digits.
    """

    value = normalize(value)

    value = value.replace(",", "")
    value = value.replace(" ", "")

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        value
    )

    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


# ==========================================
# BROWSER FETCH
# ==========================================

def fetch_page(url, prefix):
    html = None
    network_logs = []

    def on_response(response):
        try:
            request = response.request

            if request.resource_type not in ("xhr", "fetch"):
                return

            try:
                body = response.text()
            except Exception:
                body = "[Unable to read response]"

            network_logs.append(
                "\n" + "=" * 80 + "\n"
                f"STATUS: {response.status}\n"
                f"URL: {response.url}\n"
                f"METHOD: {request.method}\n"
                f"TYPE: {request.resource_type}\n"
                f"CONTENT TYPE: "
                f"{response.headers.get('content-type', '')}\n"
                f"BODY:\n{body[:100000]}\n"
            )

        except Exception as e:
            log(f"Network logging error: {e}")

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

            log(f"Opening {prefix}: {url}")

            try:
                response = page.goto(
                    url,
                    timeout=90000,
                    wait_until="domcontentloaded"
                )

                if response:
                    log(
                        f"{prefix} HTTP status: "
                        f"{response.status}"
                    )

                page.wait_for_timeout(PAGE_WAIT_SECONDS)

                html = page.content()

                visible_text = page.locator(
                    "body"
                ).inner_text()

                save_file(
                    f"{prefix.lower()}_page.html",
                    html
                )

                save_file(
                    f"{prefix.lower()}_text.txt",
                    visible_text
                )

                page.screenshot(
                    path=f"{prefix.lower()}_page.png",
                    full_page=True
                )

            except Exception as e:
                log(f"{prefix} page error: {e}")

                save_file(
                    f"{prefix.lower()}_error.txt",
                    str(e)
                )

            browser.close()

    except Exception as e:
        log(f"{prefix} browser error: {e}")

    save_file(
        f"{prefix.lower()}_network.txt",
        "\n".join(network_logs)
        if network_logs
        else "No XHR/FETCH responses captured."
    )

    return html


# ==========================================
# INVESTOR DATA EXTRACTION
# ==========================================

def extract_from_html(html):
    """
    Extract the six values from the row:
    صافي (مليون)

    Expected column order:
    Egyptian individuals
    Egyptian institutions
    Arab individuals
    Arab institutions
    Foreign individuals
    Foreign institutions
    """

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    for table in soup.find_all("table"):

        table_text = normalize(
            table.get_text(" ", strip=True)
        )

        # Validate investor table
        if not all(
            keyword in table_text
            for keyword in ("مصريين", "عرب", "اجانب")
        ):
            continue

        for row in table.find_all("tr"):

            cells = row.find_all(["td", "th"])

            if len(cells) < 7:
                continue

            first_cell = normalize(
                cells[0].get_text(" ", strip=True)
            )

            if "صافي" not in first_cell:
                continue

            values = []

            for cell in cells[1:]:
                number = parse_number(
                    cell.get_text(" ", strip=True)
                )

                if number is not None:
                    values.append(number)

            if len(values) < 6:
                continue

            result = {
                name: values[index]
                for name, index in INVESTORS
            }

            log(f"Investor values extracted: {result}")

            return result

    return None


def get_investor_data():
    """
    Sigma is the primary source.
    EGX is the fallback source.

    A source is accepted only if it contains
    the complete investor table and net row.
    """

    log("Trying Sigma Capital...")

    sigma_html = fetch_page(
        SIGMA_URL,
        "SIGMA"
    )

    data = extract_from_html(sigma_html)

    if data is not None:
        log("Successfully extracted data from Sigma.")
        return data, "Sigma Capital"

    log("Sigma extraction failed. Trying EGX...")

    egx_html = fetch_page(
        EGX_URL,
        "EGX"
    )

    data = extract_from_html(egx_html)

    if data is not None:
        log("Successfully extracted data from EGX.")
        return data, "EGX"

    log("Both sources failed to provide the required table.")

    return None, None


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):

    if not TOKEN or not CHAT_ID:
        log("Telegram credentials are missing.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        if response.ok:
            log("Telegram message sent.")
            return True

        log(f"Telegram error: {response.text}")

    except Exception as e:
        log(f"Telegram request failed: {e}")

    return False



def format_message(data, source):

    now = datetime.now(TIMEZONE)

    lines = [
        "EGX - Investor Net Transactions",
        "",
        f"Date: {now.strftime('%Y-%m-%d')}",
        f"Time: {now.strftime('%H:%M:%S')}",
        "",
        "Net Transactions (EGP Million)",
        ""
    ]

    groups = [
        ("🇪🇬 المصريين", ["مصريين أفراد", "مصريين مؤسسات"]),
        ("🌍 العرب", ["عرب أفراد", "عرب مؤسسات"]),
        ("🌐 الأجانب", ["أجانب أفراد", "أجانب مؤسسات"])
    ]

    for title, names in groups:

        lines.append(title)

        for name in names:

            value = data[name]
            formatted = f"{value:+,.2f}"

            if value > 0:
                indicator = "🟢"
            elif value < 0:
                indicator = "🔴"
            else:
                indicator = "⚪"

            lines.append(
                f"{indicator} {name}: {formatted} مليون"
            )

        lines.append("")

    return "\n".join(lines)



# ==========================================
# MAIN LOOP
# ==========================================


if __name__ == "__main__":

    now = datetime.now(TIMEZONE)

    # Sunday to Thursday
    if now.weekday() not in (6, 0, 1, 2, 3):
        log("Outside trading days. Exiting.")
        exit()

    # Allowed Cairo time: 10:15 AM to 2:45 PM
    current_minutes = now.hour * 60 + now.minute

    start_minutes = 10 * 60 + 15
    end_minutes = 14 * 60 + 45

    if not start_minutes <= current_minutes <= end_minutes:
        log("Outside sending hours. Exiting.")
        exit()

    # Allow up to 4 minutes of GitHub scheduling delay
    if now.minute % 15 > 4:
        log("Outside the scheduled execution window. Exiting.")
        exit()

    log("Starting EGX investor scraper.")

    try:
        data, source = get_investor_data()

        if data:
            message = format_message(data, source)
            print("\n" + message)
            send_telegram(message)
        else:
            log("No valid investor data found.")

            send_telegram(
                "EGX Scraper Warning\n"
                "Could not retrieve the six investor values.\n"
                "Check GitHub Actions artifacts."
            )

    except Exception as e:
        log(f"Unexpected error: {e}")

        send_telegram(
            f"EGX scraper error:\n{str(e)[:1000]}"
        )

    log("Scraper finished.")
