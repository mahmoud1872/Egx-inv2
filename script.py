import time

# ... (Keep your get_data() and send() functions exactly as they are above) ...

if __name__ == "__main__":
  # Run every 20 minutes for a duration that covers 10:20 AM to 2:40 PM (approx. 13 runs)
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

    # Wait 20 minutes before the next run (skip waiting on the very last run)
    if run_idx < total_runs - 1:
      print(f"Waiting 20 minutes for the next update...")
      time.sleep(interval_seconds)
