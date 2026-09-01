import asyncio
import os
import subprocess
import sys
import threading
import time
import atexit

from app.runtime.server import run_server

BRIDGE_EXE_PATHS = [
    os.path.join("whatsapp-mcp", "whatsapp-bridge", "whatsapp-bridge.exe"),
    os.path.join("whatsapp-mcp", "whatsapp-bridge", "whatsapp-client.exe"),
]

bridge_process = None


def cleanup():
    global bridge_process
    if bridge_process and bridge_process.poll() is None:
        print("\nShutting down WhatsApp bridge...")
        bridge_process.terminate()
        try:
            bridge_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            bridge_process.kill()


atexit.register(cleanup)


def read_output(pipe):
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    for line in iter(pipe.readline, ""):
        if not line:
            break
        line_str = line.strip()
        lower_line = line_str.lower()
        if any(keyword in lower_line for keyword in ["qr code", "waiting", "connected", "scan this", "rest server"]):
            normalized = line_str.encode("utf-8", errors="replace").decode("utf-8")
            print(f"  [WhatsApp Bridge] {normalized}")
    pipe.close()


def start_bridge():
    global bridge_process
    exe_path = None
    for p in BRIDGE_EXE_PATHS:
        if os.path.exists(p):
            exe_path = p
            break

    if not exe_path:
        print("\n[Warning] WhatsApp bridge executable not found. Did you compile it?")
        print("          Expected one of: " + ", ".join(BRIDGE_EXE_PATHS))
        print("          Jarvis will run, but WhatsApp tools may fail.\n")
        return

    print(f"\nStarting background WhatsApp bridge from {exe_path}...")

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    bridge_process = subprocess.Popen(
        [exe_path],
        cwd=os.path.dirname(exe_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        startupinfo=startupinfo,
    )

    t = threading.Thread(target=read_output, args=(bridge_process.stdout,))
    t.daemon = True
    t.start()
    time.sleep(2)


def start_runtime_server():
    print("Starting runtime WebSocket server on ws://127.0.0.1:8765")
    try:
        asyncio.run(run_server(host="127.0.0.1", port=8765))
    except OSError as exc:
        if getattr(exc, "errno", None) in {10048, 98}:
            print("\nRuntime WebSocket server already running on ws://127.0.0.1:8765; reusing the existing instance.")
            return
        raise
    except KeyboardInterrupt:
        print("\nRuntime server stopped.")


def start_http_server():
    import uvicorn

    print("Starting HTTP UI server on http://127.0.0.1:8000")
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, log_level="info")


def main():
    start_bridge()
    runtime_thread = threading.Thread(target=start_runtime_server, daemon=True)
    runtime_thread.start()
    try:
        start_http_server()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        cleanup()


if __name__ == "__main__":
    main()

