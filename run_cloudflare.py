"""Cloudflare Tunnel Launcher for local backend testing.

Replaces Ngrok with 100% Free, zero-card, zero-login Cloudflare Quick Tunnels.

Usage:
    python run_cloudflare.py                # Tunnels backend API on port 8001 (default)
    python run_cloudflare.py --port 8000    # Tunnels backend API on port 8000

Non-technical-friendly behavior (new):
    - The moment the new tunnel link is ready, a small popup window appears
      showing the link with a "Copy Link" button — one click, no selecting
      text in a terminal, no right-click menus.
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


def show_copy_link_popup(url: str) -> None:
    """Pop up a small window with the link and a one-click Copy button.

    Uses tkinter (ships with standard Python on Windows) so there's no extra
    dependency to install. Runs in a background thread so it doesn't block
    the tunnel's own output loop; the popup can be closed and the tunnel
    keeps running.
    """
    def _run():
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("VCET CSD SMS — New Link Ready")
            root.attributes("-topmost", True)
            root.resizable(False, False)

            tk.Label(root, text="New backend link is live:", font=("Segoe UI", 10)).pack(padx=16, pady=(14, 4))

            entry = tk.Entry(root, width=48, font=("Segoe UI", 10), justify="center")
            entry.insert(0, url)
            entry.config(state="readonly")
            entry.pack(padx=16, pady=4)

            status = tk.Label(root, text="", font=("Segoe UI", 9), fg="green")
            status.pack(pady=(0, 4))

            def do_copy():
                root.clipboard_clear()
                root.clipboard_append(url)
                root.update()  # keeps clipboard content after the window closes
                status.config(text="Copied! You can paste it now (Ctrl+V).")

            tk.Button(root, text="Copy Link", command=do_copy, font=("Segoe UI", 10, "bold"), bg="#f38020", fg="white", padx=12, pady=4).pack(pady=(0, 14))

            root.mainloop()
        except Exception as exc:
            print(f"[!] Could not show copy-link popup: {exc}")

    if not sys.platform.startswith("win"):
        return
    import threading
    threading.Thread(target=_run, daemon=True).start()


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
                    print("[*] A popup window has opened with a Copy Link button.")
                    print("[*] Press CTRL+C to stop the tunnel.\n")
                    print("============================================================\n")

                    show_copy_link_popup(tunnel_url)

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