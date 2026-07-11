import json
import os
import sys

# Ensure agent imports work correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import post_agent

SCHEDULE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schedule.json"
)


def main():
    if not os.path.exists(SCHEDULE_FILE):
        print(f"Error: schedule.json not found at {SCHEDULE_FILE}")
        sys.exit(1)

    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    updated = False
    for entry in schedule:
        # Check if the entry needs a post generated
        if "post_text" not in entry or not entry["post_text"]:
            topic_text = entry.get("topic", "").strip()
            details_text = entry.get("details", "").strip()

            if not topic_text:
                continue

            print(f"\n--- Generating post for: '{topic_text}' ---")
            topic = {"topic": topic_text, "details": details_text}
            try:
                post_text, _ = post_agent.run(topic)
                entry["post_text"] = post_text
                updated = True
                print("Draft generated successfully.")
            except Exception as e:
                print(f"Error generating post draft for '{topic_text}': {e}")

    if updated:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, indent=2, ensure_ascii=False)
        print("\nSuccessfully updated schedule.json with generated drafts!")
    else:
        print("\nAll scheduled topics already have pre-generated drafts.")


if __name__ == "__main__":
    main()
