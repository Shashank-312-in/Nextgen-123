"""Cloudflare Tunnel Launcher for local backend testing.

Replaces Ngrok with 100% Free, zero-card, zero-login Cloudflare Quick Tunnels.

Usage:
    python run_cloudflare.py                # Tunnels backend API on port 8001 (default)
    python run_cloudflare.py --port 8000    # Tunnels backend API on port 8000
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_EXE = os.path.join(PROJECT_ROOT, "cloudflared.exe")


def get_cloudflared_path() -> str:
    if os.path.exists(CLOUDFLARED_EXE):
        return CLOUDFLARED_EXE
    # Check system PATH
    try:
        res = subprocess.run(["cloudflared", "--version"], capture_output=True, text=True)
        if res.returncode == 0:
            return "cloudflared"
    except Exception:
        pass
    print("[!] Error: cloudflared executable not found.")
    print("[!] Download it or ensure cloudflared.exe is present in the project root.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Quick Tunnel Launcher")
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Local port to tunnel (default: 8001 for FastAPI backend)",
    )
    args = parser.parse_args()

    binary = get_cloudflared_path()
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    print("\n============================================================")
    print("         VCET CSD SMS — Cloudflare Testing Tunnel          ")
    print("============================================================")
    print(f"[*] Starting Cloudflare Tunnel for http://127.0.0.1:{args.port} ...\n")

    cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{args.port}"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    tunnel_url = None

    try:
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                match = url_pattern.search(line)
                if match and not tunnel_url:
                    tunnel_url = match.group(0)
                    print(f"\n[+] LIVE CLOUDFLARE PUBLIC URL:")
                    print(f"    URL: {tunnel_url}\n")
                    print(f"[*] Copy this URL and set VITE_API_URL on Vercel/Render!")
                    print("[*] Press CTRL+C to stop the tunnel.\n")
                    print("============================================================\n")

        process.wait()
    except KeyboardInterrupt:
        print("\n[*] Shutting down Cloudflare Tunnel...")
        process.terminate()
        try:
            process.wait(timeout=3)
        except Exception:
            process.kill()
        print("[*] Cloudflare Tunnel stopped.")


if __name__ == "__main__":
    main()
