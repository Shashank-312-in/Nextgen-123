#!/usr/bin/env python3
"""Runner script to execute test files one by one and record their output log into a file."""
import glob
import os
import subprocess
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_ROOT, "test_results.log")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

test_files = sorted(glob.glob(os.path.join(PROJECT_ROOT, "tests", "test_*.py")))

if not test_files:
    print("No test files found in tests/ directory.")
    sys.exit(1)

divider = "=" * 80
start_time = datetime.now()

header = f"""{divider}
NextGen SMS Test Suite — Sequential Test Execution Run
Timestamp : {start_time.strftime('%Y-%m-%d %H:%M:%S')}
Test Files: {len(test_files)} files detected
Output Log: {LOG_FILE}
{divider}
"""

print(header)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write(header + "\n")

summary_results = []

for idx, test_file in enumerate(test_files, start=1):
    test_rel = os.path.relpath(test_file, PROJECT_ROOT)
    module_name = os.path.basename(test_file)
    banner = f"\n{divider}\n[{idx}/{len(test_files)}] Running: {test_rel}\n{divider}\n"
    print(banner, flush=True)
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(banner + "\n")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "-v",
        "--tb=short",
    ]

    t0 = time.time()
    env = dict(os.environ)
    env["SMS_PROJECT_ROOT"] = PROJECT_ROOT

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=PROJECT_ROOT,
    )

    output_lines = []
    with open(LOG_FILE, "a", encoding="utf-8") as log_f:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
            output_lines.append(line)

    proc.wait()
    elapsed = time.time() - t0
    exit_code = proc.returncode
    status = "PASSED" if exit_code == 0 else f"FAILED (exit {exit_code})"
    summary_results.append((module_name, status, f"{elapsed:.2f}s"))

end_time = datetime.now()
total_duration = (end_time - start_time).total_seconds()

footer = f"""
{divider}
FINAL SUMMARY OF TEST RUNS
Total Duration: {total_duration:.2f}s
Finished At   : {end_time.strftime('%Y-%m-%d %H:%M:%S')}
{divider}
"""
for name, status, dur in summary_results:
    footer += f"  - {name:<32} : {status:<15} ({dur})\n"
footer += f"{divider}\nAll logs saved to: {LOG_FILE}\n"

print(footer)
with open(LOG_FILE, "a", encoding="utf-8") as f:
    f.write(footer + "\n")
