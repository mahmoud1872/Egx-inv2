import io
import os
import time
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
      # Extra padding time for dynamic client-side JS rendering
      page.wait_for_timeout(7000)
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

  try:
    # Read all tables found on the page via pandas
    dfs = pd.read_html(io.StringIO(html_content))
    print(f"Successfully parsed {len(dfs)} tables from page HTML.")

    for df in dfs:
      df_str = df.to_string()
      for keyword, target_name in targets:
        if keyword in df_str and target_name not in extracted_data:
          records = []
          for _, row in df.iterrows():
            row_vals = [str(val).strip() for val in row.values if pd.notna(val)]
            if len(row_vals) >= 2:
              # Typically column 0 is Nationality and the last column is Net Value (صافي)
              records.append({
                  "جنسية": row_vals[0],
                  "صافي قيمة جنيه مصري": row_vals[-1],
              })
          if records:
            extracted_data[target_name] = records
  except Exception as e:
    print(f"Error parsing tables with pandas: {e}")

  return extracted_data if extracted_data else None


def send(text):
  url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
  try:
    response = requests.post(
        url, data={"chat_id": CHAT_ID, "text": text}, timeout=20
    )
    if not response.ok:
      print(f"Failed to send Telegram message: {response.text}")
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
      if TOKEN and CHAT_ID:
        send(final_message)
    else:
      print("No data tables matched.")
      if TOKEN and CHAT_ID:
        send("No data found or failed to scrape EGX website.")

    if run_idx < total_runs - 1:
      print("Waiting 20 minutes for the next update...")
      time.sleep(interval_seconds)
