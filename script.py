import io
import os
import time
from bs4 import BeautifulSoup
import pandas as pd
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
URL = "https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx"


def get_data():
  print("Launching headless browser to fetch EGX page...")
  try:
    with sync_playwright() as p:
      browser = p.chromium.launch(
          headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
      )
      page = browser.new_page()
      page.goto(URL, timeout=90000, wait_until="networkidle")
      # Wait for dynamic elements to render completely
      page.wait_for_timeout(8000)
      html_content = page.content()
      browser.close()
  except Exception as e:
    print(f"Playwright error: {e}")
    return None

  extracted_data = {}
  targets = [
      ("الافراد", "الافراد حسب الجنسيه"),
      ("المؤسسات", "المؤسسات حسب الجنسيه"),
  ]

  # 1. Try parsing via pandas read_html
  try:
    dfs = pd.read_html(io.StringIO(html_content))
    print(f"Successfully parsed {len(dfs)} tables from page HTML via pandas.")
    for idx, df in enumerate(dfs):
      df_str = df.to_string()
      for keyword, target_name in targets:
        if keyword in df_str and target_name not in extracted_data:
          records = []
          for _, row in df.iterrows():
            row_vals = [str(val).strip() for val in row.values if pd.notna(val)]
            if len(row_vals) >= 2:
              records.append({
                  "جنسية": row_vals[0],
                  "صافي قيمة جنيه مصري": row_vals[-1],
              })
          if records:
            extracted_data[target_name] = records
  except Exception as e:
    print(f"Pandas read_html warning: {e}")

  # 2. Fallback: BeautifulSoup deep scan if pandas missed anything
  if len(extracted_data) < len(targets):
    print(
        "Running BeautifulSoup deep scan fallback for missing sections..."
    )
    soup = BeautifulSoup(html_content, "html.parser")
    for keyword, target_name in targets:
      if target_name in extracted_data:
        continue
      # Find any tag containing the keyword
      heading_el = soup.find(
          lambda tag: tag.name in ["div", "span", "h2", "h3", "h4", "th", "td"]
          and tag.get_text()
          and keyword in tag.get_text()
      )
      if heading_el:
        table = heading_el.find_parent("table") or heading_el.find_next("table")
        if table:
          rows = table.find_all("tr")
          records = []
          for tr in rows:
            cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cols) >= 2:
              records.append({"جنسية": cols[0], "صافي قيمة جنيه مصري": cols[-1]})
          if records:
            extracted_data[target_name] = records

  # Diagnostic print if still empty
  if not extracted_data:
    print(
        "--- DIAGNOSTIC: Page text snippet ---"
    )
    soup_diag = BeautifulSoup(html_content, "html.parser")
    print(soup_diag.get_text()[:500])  # Print first 500 chars of page text

  return extracted_data if extracted_data else None


def send(text):
  if not TOKEN or not CHAT_ID:
    print("Telegram credentials (TOKEN or CHAT_ID) are missing!")
    return
  url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
  try:
    response = requests.post(
        url, data={"chat_id": CHAT_ID, "text": text}, timeout=20
    )
    if not response.ok:
      print(f"Failed to send Telegram message: {response.text}")
    else:
      print("Telegram message sent successfully.")
  except Exception as e:
    print(f"Telegram request failed: {e}")


if __name__ == "__main__":
  total_runs = 13
  interval_seconds = 1200  # 20 minutes

  for run_idx in range(total_runs):
    print(f"\n--- Run {run_idx + 1} of {total_runs} ---")
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
      send(final_message)
    else:
      print("No matching data tables found.")
      send(
          "No data found or failed to scrape EGX website during scheduled run."
      )

    if run_idx < total_runs - 1:
      print("Waiting 20 minutes for the next update...")
      time.sleep(interval_seconds)
