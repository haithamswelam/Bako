## ---------------------------------------------------------------
## BAKO APP LAUNCHER - turns the dashboard into a desktop window.
## What it does, in order:
##   1. starts the dashboard server in the background (no browser tab, no console)
##   2. waits until the server answers
##   3. opens a native window titled "Bako" (needs: pip install pywebview)
##      - without pywebview it opens your normal browser instead
##   4. when you close the window, it stops the server
## Double-click Bako.bat in the repo root to run this. It always uses the project's
## own Python (agent/.venv), so the "No module named ..." problem cannot happen.
## ---------------------------------------------------------------
import os, socket, subprocess, sys, time, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PORT = int(os.environ.get("BAKO_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"
GIT_BASH = r"C:\Program Files\Git\usr\bin\bash.exe"

def port_open():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
        return True
    except OSError:
        return False

def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    ## A double-clicked program may find WSL's bash first. Pin Git's bash like agent.py does.
    if not env.get("AGENT_BASH") and os.path.exists(GIT_BASH):
        env["AGENT_BASH"] = GIT_BASH

    server = None
    if port_open():
        print(f"Dashboard already running on {URL}, opening a window to it.")
    else:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)       # Windows: no extra console window
        server = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "dashboard.py"),
             "--server.address", "127.0.0.1", "--server.port", str(PORT),
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=REPO, env=env, creationflags=flags)
        for _ in range(120):                                      # wait up to 60 seconds
            if port_open():
                break
            if server.poll() is not None:
                raise SystemExit("The dashboard server stopped at start-up. Run Bako-debug.bat to see why.")
            time.sleep(0.5)
        else:
            server.terminate()
            raise SystemExit("The dashboard did not start within 60 seconds.")

    try:
        try:
            import webview                                        # pywebview: a native window
        except ImportError:
            print("pywebview is not installed (pip install pywebview): opening your browser instead.")
            webbrowser.open(URL)
            print("Close this window or press Ctrl+C to stop Bako.")
            while server is None or server.poll() is None:
                time.sleep(1)
        else:
            webview.create_window("Bako", URL, width=1500, height=950, min_size=(1000, 700))
            webview.start()                                       # returns when the window is closed
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()                                     # did not stop politely: force it

if __name__ == "__main__":
    main()