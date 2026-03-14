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
import socket

# ── Try to import websocket-client, install if missing ──────────────────────
try:
    import websocket
except ImportError:
    print("  Installing required package (websocket-client)...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client", "--quiet", "--break-system-packages"])
    import websocket

# ── Config ───────────────────────────────────────────────────────────────────
GAME_URL      = "http://localhost:8080"
RELAY_URL     = "wss://beaverops-relay.beaverops-relay.workers.dev"
POLL_INTERVAL = 5  # seconds between game polls
RECONNECT_DELAY = 5  # seconds between relay reconnect attempts

# ── State ────────────────────────────────────────────────────────────────────
ws_conn       = None
session_code  = None
running       = True
dashboard_connected = False

# ─────────────────────────────────────────────────────────────────────────────
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
        print("  Open beaverops.com and enter this code")
        print("  to view your colony dashboard.")
        print()
        print("  ─────────────────────────────────────────")
        game_ok = check_game_quick()
        print(f"  Game:      {'🟢 Connected' if game_ok else '🔴 Not running / no map loaded'}")
        relay_ok = ws_conn and ws_conn.sock and ws_conn.sock.connected
        print(f"  Relay:     {'🟢 Connected' if relay_ok else '🔴 Reconnecting...'}")
        print(f"  Dashboard: {'🟢 Viewing' if dashboard_connected else '⚫ Not open'}")
        print()
        print("  ─────────────────────────────────────────")
        print("  Press Ctrl+C to stop.")
    else:
        print("  Connecting to relay server...")
    print()

def check_game_quick():
    try:
        req = urllib.request.Request(f"{GAME_URL}/api/levers")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except:
        return False

# ─────────────────────────────────────────────────────────────────────────────
def fetch_game_data():
    """Poll the game and return combined data dict, or None if game not running."""
    try:
        def get(path):
            req = urllib.request.Request(f"{GAME_URL}{path}")
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.loads(r.read().decode())

        levers   = get("/api/levers")
        adapters = get("/api/adapters")

        # Normalize to lists in case game returns a single object
        if isinstance(levers, dict):   levers   = [levers]
        if isinstance(adapters, dict): adapters = [adapters]

        return {"levers": levers, "adapters": adapters}
    except Exception as e:
        return None

def send_lever_command(name, state):
    """Send a lever on/off command to the game."""
    try:
        endpoint = "switch-on" if state else "switch-off"
        req = urllib.request.Request(
            f"{GAME_URL}/api/{endpoint}/{urllib.parse.quote(name)}",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status == 200
    except Exception as e:
        return False

def send_color_command(name, hex_color):
    """Send a color change command to the game."""
    try:
        import urllib.parse
        req = urllib.request.Request(
            f"{GAME_URL}/api/color/{urllib.parse.quote(name)}/{hex_color.lstrip('#')}",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status == 200
    except:
        return False

# ─────────────────────────────────────────────────────────────────────────────
def poll_and_push():
    """Background thread: poll game every N seconds, push to dashboard via relay."""
    import urllib.parse
    while running:
        if ws_conn and ws_conn.sock and dashboard_connected:
            data = fetch_game_data()
            if data:
                try:
                    ws_conn.send(json.dumps({
                        "type": "game_data",
                        "payload": data
                    }))
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
    """Handle messages from the relay (forwarded from dashboard)."""
    global dashboard_connected
    import urllib.parse

    try:
        msg = json.loads(message)
    except:
        return

    msg_type = msg.get("type")

    if msg_type == "peer_connected":
        dashboard_connected = True
        print_status()
        # Immediately push fresh data
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
        ws.send(json.dumps({
            "type": "lever_result",
            "name": name,
            "state": state,
            "ok": ok
        }))
        # Push fresh data immediately after lever change
        time.sleep(0.3)
        data = fetch_game_data()
        if data:
            ws.send(json.dumps({"type": "game_data", "payload": data}))

    elif msg_type == "lever_color":
        name  = msg.get("name", "")
        color = msg.get("color", "")
        ok = send_color_command(name, color)
        ws.send(json.dumps({
            "type": "color_result",
            "name": name,
            "color": color,
            "ok": ok
        }))

    elif msg_type == "poll_now":
        # Dashboard requesting immediate data
        data = fetch_game_data()
        if data:
            ws.send(json.dumps({"type": "game_data", "payload": data}))

def on_error(ws, error):
    pass  # Handled in on_close / reconnect loop

def on_close(ws, close_status_code, close_msg):
    global dashboard_connected
    dashboard_connected = False
    print_status()

def on_open(ws):
    global session_code
    print_status()
    # Immediately push data if game is running
    data = fetch_game_data()
    if data:
        ws.send(json.dumps({"type": "game_data", "payload": data}))

# ─────────────────────────────────────────────────────────────────────────────
def get_session_code():
    """Get a new session code from the relay server."""
    try:
        req = urllib.request.Request(f"{RELAY_URL.replace('wss://', 'https://').replace('ws://', 'http://')}/session")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            return data.get("code")
    except Exception as e:
        return None

def connect_relay(code):
    """Connect to the relay as the agent for this session code."""
    url = f"{RELAY_URL}/relay/{code}/agent"
    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
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

    # Get a session code
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
        input("  Press Enter to exit...")
        sys.exit(1)

    # Start poll-and-push thread
    poll_thread = threading.Thread(target=poll_and_push, daemon=True)
    poll_thread.start()

    # Main loop: connect and reconnect
    print_status()
    while running:
        try:
            ws_conn = connect_relay(session_code)
            ws_conn.run_forever(
                ping_interval=30,
                ping_timeout=10,
                reconnect=0  # we handle reconnect ourselves
            )
        except KeyboardInterrupt:
            running = False
            break
        except Exception:
            pass

        if not running:
            break

        time.sleep(RECONNECT_DELAY)

    print()
    print("  BeaverOps Agent stopped. Good luck with the beavers! 🦫")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        running = False
        print("\n  BeaverOps Agent stopped.")
        sys.exit(0)
