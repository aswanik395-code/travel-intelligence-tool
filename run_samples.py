"""Run the tool against several countries (incl. invalid input) and save results.

    python run_samples.py
Writes sample_outputs/<country>.txt for each success and test_run_log.txt for everything.
"""
import os
import time

from travel_tool import TravelToolError, format_snapshot, get_travel_snapshot, load_config

TESTS = ["Japan", "Brazil", "Iceland", "Bhutan", "Atlantis", "12345", ""]

cfg = load_config()
os.makedirs("sample_outputs", exist_ok=True)
log = []
for name in TESTS:
    label = repr(name)
    try:
        info = get_travel_snapshot(name, cfg)
        text = format_snapshot(info)
        with open(os.path.join("sample_outputs", f"{info['country'].lower().replace(' ', '_')}.txt"),
                  "w", encoding="utf-8") as f:
            f.write(text + "\n")
        log.append(f"--- {label}: OK ---\n{text}\n")
    except TravelToolError as e:
        log.append(f"--- {label}: HANDLED ERROR ---\nError: {e}\n")
    time.sleep(1)  # stay under the API's rate limit (about 20 requests / 10 s)

output = "\n".join(log)
print(output)
with open("test_run_log.txt", "w", encoding="utf-8") as f:
    f.write(output)