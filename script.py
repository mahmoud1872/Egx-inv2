import os
import time
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
URL = "https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx"


def get_data():
  try:
    with sync_playwright() as p:
      browser = p.chromium.launch(headless=True)
      page = browser.new_page()
      page.goto(URL, timeout=60000)
      # Wait for the tables or content to load dynamically
      page.wait_for_timeout(5000)
      html_content = page.content()
      browser.close()
  except Exception as e:
    print(f"Error fetching webpage with Playwright: {e}")
    return None

  soup = BeautifulSoup(html_content, "html.parser")
  targets = ["الافراد حسب الجنسيه", "المؤسسات حسب الجنسيه"]
  extracted_data = {}

  for target in targets:
    section_tag = soup.find(
        lambda tag: tag.name in ["div", "span", "h2", "h3", "h4", "th", "td"]
        and target in tag.get_text()
    )

    if not section_tag:
      print(f"Could not find section: {target}")
      continue

    container = section_tag.find_parent("table") or section_tag.find_parent(
        "div"
    )
    table = None
    if container:
      table = container.find("table") if container.name != "table" else container

    if not table:
      print(f"Could not find table for section: {target}")
      continue

    rows = table.find_all("tr")
    table_data = []
    headers_list = []

    for idx, tr in enumerate(rows):
      cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
      if not cols:
        continue

      if idx == 0 or not headers_list:
        headers_list = cols
      else:
        table_data.append(cols)

    structured_results = []
    nationality_idx, net_egp_idx = None, None

    for i, h in enumerate(headers_list):
      if "جنسيه" in h or "الجنسية" in h:
        nationality_idx = i
      if "صافي" in h and ("جنيه" in h or "قيمه" in h or "قيمة" in h):
        net_egp_idx = i

    if nationality_idx is None:
      nationality_idx = 0
    if net_egp_idx is None:
      net_egp_idx = -1

    for row in table_data:
      if len(row) > max(nationality_idx, net_egp_idx):
        structured_results.append({
            "جنسية": row[nationality_idx],
            "صافي قيمة جنيه مصري": row[net_egp_idx],
        })
      else:
        structured_results.append({"raw_row": row})

    extracted_data[target] = structured_results

  return extracted_data if extracted_data else None


def send(text):
  url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
  response = requests.post(
      url, data={"chat_id": CHAT_ID, "text": text}, timeout=20
  )
  if not response.ok:
    print(f"Failed to send Telegram message: {response.text}")


if __name__ == "__main__":
  total_runs = 13
  interval_seconds = 1200  # 20 minutes

  for run_idx in range(total_runs):
    print(f"--- Run {run_idx + 1} of {total_runs} ---")
    data = get_data()

    if data:
      message_lines = []
      for section, records in data.items():
        message_lines.append(f"=== {section} ===")
        for record in records:
          if "جنسية" in record:
            message_lines.append(
                f"- {record['جنسية']}: {record['صافي قيمة جنيه مصري']}"
            )
          else:
            message_lines.append(f"- {record}")
        message_lines.append("")

      final_message = "\n".join(message_lines)
      print(final_message)
      if TOKEN and CHAT_ID:
        send(final_message)
    else:
      if TOKEN and CHAT_ID:
        send("No data found or failed to scrape EGX website.")

    if run_idx < total_runs - 1:
      print("Waiting 20 minutes for the next update...")
      time.sleep(interval_seconds)
