import os
import sys
import subprocess
import threading
import time
import atexit
import asyncio
from ollama_agent import run_agent

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
    for line in iter(pipe.readline, ""):
        if not line:
            break
        line_str = line.strip()
        lower_line = line_str.lower()
        # Filter what to show on console so it doesnt interrupt the agent loop
        if any(keyword in lower_line for keyword in ["qr code", "waiting", "connected", "scan this", "rest server"]):
            print(f"  [WhatsApp Bridge] {line_str}")
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
    
    # Hide console window on Windows
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
        startupinfo=startupinfo
    )

    t = threading.Thread(target=read_output, args=(bridge_process.stdout,))
    t.daemon = True
    t.start()
    
    # Wait briefly to let the bridge print QR or startup messages before Jarvis clears/prints banner
    time.sleep(2)

if __name__ == "__main__":
    try:
        start_bridge()
        import uvicorn
        uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        cleanup()

