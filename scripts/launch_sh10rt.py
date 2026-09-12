#!/usr/bin/env python3
"""Shared terminal launcher; all inverter operations stay in sh10rt_lan.py."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "scripts" / "sh10rt_lan.py"
ENVIRONMENT = ROOT / ".launcher-venv"


def winet_python():
    """Reuse an available client or install it into an isolated local environment."""
    if importlib.util.find_spec("websocket") is not None:
        return sys.executable
    python = ENVIRONMENT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    try:
        if not python.is_file():
            print("Preparing a local Python environment for WiNet...", file=sys.stderr, flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(ENVIRONMENT)], check=True,
                           stdout=sys.stderr)
        available = subprocess.run([str(python), "-c", "import websocket"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if available.returncode != 0:
            print("Installing the WiNet dependency (internet access required)...", file=sys.stderr, flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                            "-r", str(ROOT / "scripts" / "requirements.txt")], check=True,
                           stdout=sys.stderr)
        return str(python)
    except (OSError, subprocess.CalledProcessError):
        print("WiNet setup failed. Install Python's venv/pip support, then retry. "
              "See NETWORK-SCRIPTS.md. Scan and Modbus still work without this dependency.",
              file=sys.stderr)
        return None


def run_tool(arguments):
    # Parse with the tool itself before setup: --help and invalid input stay offline.
    from sh10rt_lan import make_parser
    args = make_parser().parse_args(arguments)
    python = sys.executable
    if getattr(args, "transport", None) == "winet":
        python = winet_python()
        if python is None:
            return 2
    # Never add --execute, infer a device/serial, or retry a command.
    return subprocess.run([python, str(TOOL), *arguments]).returncode


def menu():
    print("SH10RT LAN tool\nConnect this computer to the inverter LAN or its VPN.")
    while True:
        print("\n1. Find inverter interfaces (read only)\n2. Read inverter status"
              "\n3. Preview Start (no command sent)\n4. Show inverter measurements\n0. Exit")
        choice = input("Choose: ").strip()
        if choice == "0":
            return 0
        if choice == "1":
            arguments = ["scan", "--network", input("LAN subnet (example: 192.168.1.0/24): ").strip()]
        elif choice in ("2", "3", "4"):
            host = input("Inverter/interface IPv4 address: ").strip()
            transport = input("Connection: modbus or winet [modbus]: ").strip().lower() or "modbus"
            arguments = [{"2": "status", "3": "start", "4": "values"}[choice],
                         "--host", host, "--transport", transport]
            if transport == "winet":
                arguments += ["--username", input("WiNet username [admin]: ").strip() or "admin"]
            elif transport == "modbus":
                arguments += ["--unit", input("Modbus unit ID [1]: ").strip() or "1"]
            if choice == "3":
                arguments += ["--serial", input("Exact serial of the intended inverter: ").strip()]
        else:
            print("Choose 0, 1, 2, 3 or 4.")
            continue
        try:
            result = run_tool(arguments)
        except SystemExit as exc:
            result = exc.code
        print(f"\nFinished with exit code {result}.")
        if choice == "3":
            print("This was a read-only preview. For an explicit Start, use the terminal "
                  "command with --serial and --execute described in NETWORK-SCRIPTS.md.")


def main():
    if sys.version_info < (3, 10):
        print("Python 3.10 or later is required.", file=sys.stderr)
        return 2
    try:
        if sys.argv[1:]:
            return run_tool(sys.argv[1:])
        if not sys.stdin.isatty():
            return run_tool(["--help"])
        return menu()
    except (EOFError, KeyboardInterrupt):
        print("\nInterrupted. Any command already sent may still take effect; inspect status before retrying.",
              file=sys.stderr)
        return 130
    except OSError:
        print("Unable to run the Python tool. Check your Python installation and folder permissions.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
