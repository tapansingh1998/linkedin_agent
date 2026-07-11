import json
import os
import sys
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv

load_dotenv()

SCHEDULE_FILE = "schedule.json"

if not os.path.exists(SCHEDULE_FILE):
    print("No schedule.json found.")
    sys.exit(0)

with open(SCHEDULE_FILE) as f:
    schedule = json.load(f)

# Get current date in YYYY-MM-DD
today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
print(f"Checking schedule for today: {today_str}")

matching_entry = None
for entry in schedule:
    if entry.get("date") == today_str:
        matching_entry = entry
        break

if not matching_entry:
    print("No post scheduled for today.")
    sys.exit(0)

topic = matching_entry.get("topic")
details = matching_entry.get("details", "")

print(f"Found scheduled post: {topic}")

app_url = os.getenv("APP_BASE_URL", "http://localhost:8000")
secret_key = os.getenv("SECRET_KEY")

if not secret_key:
    print("Error: SECRET_KEY environment variable not set.")
    sys.exit(1)

endpoint = f"{app_url}/run-scheduled"
print(f"Triggering: {endpoint}")

try:
    resp = httpx.post(
        endpoint,
        json={
            "topic": topic,
            "details": details,
            "secret_key": secret_key
        },
        timeout=60
    )
    resp.raise_for_status()
    print("Successfully triggered post generation. Check email for approval.")
except Exception as e:
    print(f"Error triggering Render API: {e}")
    sys.exit(1)
