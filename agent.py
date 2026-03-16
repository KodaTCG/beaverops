#!/usr/bin/env python3
"""
BeaverOps Agent
Bridges your local Timberborn game to the BeaverOps relay server
so you can view the dashboard from any device, anywhere.

Usage: double-click start-agent.bat (Windows) or run python agent.py
"""

import json
import time
import sys
import os
import threading
import urllib.request
import urllib.error
import urllib.parse

# ── Try to import websocket-client, install if missing ──────────────────────
try:
    import websocket
except ImportError:
    print("  Installing required package (websocket-client)...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client", "--quiet"])
    import websocket

# ── Config ───────────────────────────────────────────────────────────────────
GAME_URL        = "http://localhost:8080"
RELAY_HTTP_URL  = "https://beaverops-relay.kodatcg.workers.dev"
RELAY_WS_URL    = "wss://beaverops-relay.kodatcg.workers.dev"
POLL_INTERVAL   = 5
RECONNECT_DELAY = 5

# ── State ────────────────────────────────────────────────────────────────────
ws_conn             = None
session_code        = None
running             = True
dashboard_connected = False

# ─────────────────────────────────────────────────────────────────────────────

def safe_input(prompt):
    """input() that won't crash when stdin is unavailable (compiled exe)."""
    try:
        return input(prompt)
    except Exception:
        time.sleep(5)
        return ""

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_status():
    clear()
    print()
    print("  ==========================================")
    print("   BEAVEROPS AGENT")
    print("  ==========================================")
    print()
    if session_code:
        print(f"  Your session code:  {session_code}")
        print()
        print("  Open beaverops.vercel.app and enter")
        print("  this code to view your colony dashboard.")
        print()
        print("  ------------------------------------------")
        game_ok = check_game_quick()
        relay_ok = ws_conn is not None and getattr(ws_conn, 'sock', None) is not None
        print(f"  Game:      {'OK  - Connected' if game_ok else 'WAIT - Not running / no map loaded'}")
        print(f"  Relay:     {'OK  - Connected' if relay_ok else 'WAIT - Reconnecting...'}")
        print(f"  Dashboard: {'OK  - Viewing' if dashboard_connected else 'WAIT - Not open yet'}")
        print()
        print("  ------------------------------------------")
        print("  Press Ctrl+C to stop.")
    else:
        print("  Connecting to relay server...")
    print()

def check_game_quick():
    try:
        req = urllib.request.Request(f"{GAME_URL}/api/levers")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────

def fetch_game_data():
    """Poll the game and return combined data dict, or None if game not running."""
    try:
        def get(path):
            req = urllib.request.Request(f"{GAME_URL}{path}")
            with urllib.request.urlopen(req, timeout=4) as r:
                data = json.loads(r.read().decode())
                if isinstance(data, dict):
                    data = [data]
                return data

        levers   = get("/api/levers")
        adapters = get("/api/adapters")
        return {"levers": levers, "adapters": adapters}
    except Exception:
        return None

def send_lever_command(name, state):
    try:
        endpoint = "switch-on" if state else "switch-off"
        req = urllib.request.Request(
            f"{GAME_URL}/api/{endpoint}/{urllib.parse.quote(name)}",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status == 200
    except Exception:
        return False

def send_color_command(name, hex_color):
    try:
        req = urllib.request.Request(
            f"{GAME_URL}/api/color/{urllib.parse.quote(name)}/{hex_color.lstrip('#')}",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status == 200
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────

def poll_and_push():
    """Background thread: poll game every N seconds, push to dashboard."""
    while running:
        if ws_conn and dashboard_connected:
            data = fetch_game_data()
            if data:
                try:
                    ws_conn.send(json.dumps({"type": "game_data", "payload": data}))
                except Exception:
                    pass
            else:
                try:
                    ws_conn.send(json.dumps({
                        "type": "game_offline",
                        "message": "Game not running or no map loaded"
                    }))
                except Exception:
                    pass
        time.sleep(POLL_INTERVAL)

# ─────────────────────────────────────────────────────────────────────────────

def on_message(ws, message):
    global dashboard_connected
    try:
        msg = json.loads(message)
    except Exception:
        return

    msg_type = msg.get("type")

    if msg_type == "peer_connected":
        dashboard_connected = True
        print_status()
        data = fetch_game_data()
        if data:
            ws.send(json.dumps({"type": "game_data", "payload": data}))

    elif msg_type == "peer_disconnected":
        dashboard_connected = False
        print_status()

    elif msg_type == "lever_toggle":
        name  = msg.get("name", "")
        state = msg.get("state", False)
        ok = send_lever_command(name, state)
        ws.send(json.dumps({"type": "lever_result", "name": name, "state": state, "ok": ok}))
        time.sleep(0.3)
        data = fetch_game_data()
        if data:
            ws.send(json.dumps({"type": "game_data", "payload": data}))

    elif msg_type == "lever_color":
        name  = msg.get("name", "")
        color = msg.get("color", "")
        ok = send_color_command(name, color)
        ws.send(json.dumps({"type": "color_result", "name": name, "color": color, "ok": ok}))

    elif msg_type == "poll_now":
        data = fetch_game_data()
        if data:
            ws.send(json.dumps({"type": "game_data", "payload": data}))

def on_error(ws, error):
    pass

def on_close(ws, close_status_code, close_msg):
    global dashboard_connected
    dashboard_connected = False
    print_status()

def on_open(ws):
    print_status()
    data = fetch_game_data()
    if data:
        ws.send(json.dumps({"type": "game_data", "payload": data}))

# ─────────────────────────────────────────────────────────────────────────────

def get_session_code():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(
            f"{RELAY_HTTP_URL}/session",
            headers={"User-Agent": "BeaverOpsAgent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            data = json.loads(r.read().decode())
            return data.get("code")
    except Exception as e:
        print(f"  [debug] failed: {type(e).__name__}: {e}")
        return None

def connect_relay(code):
    import ssl
    url = f"{RELAY_WS_URL}/relay/{code}/agent"
    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    # Store ssl_opt on the ws for use in run_forever
    ws._ssl_opt = {"cert_reqs": ssl.CERT_NONE}
    return ws

# ─────────────────────────────────────────────────────────────────────────────

def main():
    global ws_conn, session_code, running

    print()
    print("  ==========================================")
    print("   BEAVEROPS AGENT - Starting up...")
    print("  ==========================================")
    print()
    print("  Getting session code from relay server...")

    for attempt in range(5):
        code = get_session_code()
        if code:
            session_code = code
            break
        print(f"  Retrying... ({attempt + 1}/5)")
        time.sleep(2)

    if not session_code:
        print()
        print("  ERROR: Could not reach the BeaverOps relay server.")
        print("  Check your internet connection and try again.")
        print()
        safe_input("  Press Enter to exit...")
        sys.exit(1)

    poll_thread = threading.Thread(target=poll_and_push, daemon=True)
    poll_thread.start()

    print_status()

    while running:
        try:
            ws_conn = connect_relay(session_code)
            ssl_opt = getattr(ws_conn, '_ssl_opt', {})
            ws_conn.run_forever(ping_interval=30, ping_timeout=10, sslopt=ssl_opt)
        except KeyboardInterrupt:
            running = False
            break
        except Exception:
            pass

        if not running:
            break

        time.sleep(RECONNECT_DELAY)

    print()
    print("  BeaverOps Agent stopped. Good luck with the beavers!")

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        running = False
        print("\n  BeaverOps Agent stopped.")
        sys.exit(0)
