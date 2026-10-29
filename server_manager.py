"""
Comprehensive Server Management Controller for Contract Note Parser Web Application.

Provides an all-in-one CLI and interactive interface to:
  - Start the web server in the background with process tracking
  - Gracefully stop the server and release ports
  - Restart the server cleanly
  - Report detailed server status (Health, PID, Uptime, Memory, Local URL, Network URL, Public Website Link)
  - Configure and persist the live website deployment link
  - Generate an instant public web link (via cloudflared/ngrok/localtunnel)
  - View live logs and open the interface directly in the browser

Usage:
  python server_manager.py start
  python server_manager.py stop
  python server_manager.py restart
  python server_manager.py status
  python server_manager.py set-url <url>
  python server_manager.py url
  python server_manager.py open
  python server_manager.py logs [lines]
  python server_manager.py tunnel
  python server_manager.py                (Interactive Menu)
"""

import os
import sys
import time
import json
import socket
import signal
import urllib.request
import urllib.error
import subprocess
import webbrowser
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

# Reconfigure stdout/stderr for safe UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PID_FILE = os.path.join(BASE_DIR, ".server.pid")
LOG_FILE = os.path.join(BASE_DIR, "server.log")
APP_SCRIPT = os.path.join(BASE_DIR, "app.py")

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 5000,
    "website_url": "https://file-parser-r7b0.onrender.com",
    "github_url": "https://github.com/Arham-1313/file_parser",
    "project_name": "Contract Note Parser & Financial Web Platform",
    "author_name": "Arham Begani",
    "project_type": "Personal Open Source Project"
}

# ANSI Color codes for friendly console UI
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'

# Enable ANSI colors on Windows console
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json or initialize with defaults."""
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg: Dict[str, Any]) -> None:
    """Save configuration to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"{Colors.RED}[!] Error saving config: {e}{Colors.RESET}")


def update_config_value(key: str, value: Any) -> None:
    """Update a single configuration key."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


def find_best_python() -> str:
    """Find a Python interpreter that has the required dependencies (pdfplumber) installed."""
    # 1. Test current running interpreter
    try:
        res = subprocess.run([sys.executable, "-c", "import pdfplumber"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return sys.executable
    except Exception:
        pass

    # 2. On Windows, check other Python versions via py launcher
    if sys.platform == "win32":
        for ver in ["-3.14", "-3.12", "-3.11", "-3.13", "-3"]:
            try:
                cmd = ["py", ver, "-c", "import pdfplumber; import sys; print(sys.executable)"]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                if out and os.path.exists(out):
                    return out
            except Exception:
                pass

    return sys.executable


def get_local_ip() -> str:
    """Get the primary local IPv4 address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a network port is currently open and bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        result = s.connect_ex((host, port))
        return result == 0


def get_stored_pid_info() -> Tuple[Optional[int], Optional[float]]:
    """Retrieve the PID and start timestamp stored in the PID file."""
    if not os.path.exists(PID_FILE):
        return None, None
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None, None
            parts = content.split(",")
            pid = int(parts[0])
            start_time = float(parts[1]) if len(parts) > 1 else None
            return pid, start_time
    except Exception:
        return None, None


def save_pid(pid: int) -> None:
    """Save process ID and current timestamp to PID file."""
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(f"{pid},{time.time()}")
    except Exception as e:
        print(f"{Colors.YELLOW}[!] Warning: Could not write PID file: {e}{Colors.RESET}")


def remove_pid_file() -> None:
    """Remove the PID file."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is actively running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /NH', shell=True, text=True, stderr=subprocess.DEVNULL)
            return str(pid) in out
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def get_process_metrics(pid: int) -> Dict[str, Any]:
    """Obtain memory and CPU statistics for the process if available."""
    metrics = {"memory_mb": None, "cpu_percent": None}
    try:
        import psutil
        p = psutil.Process(pid)
        metrics["memory_mb"] = round(p.memory_info().rss / (1024 * 1024), 2)
        metrics["cpu_percent"] = p.cpu_percent(interval=0.1)
    except Exception:
        pass
    return metrics


def check_http_health(port: int) -> Tuple[bool, Optional[Dict[str, Any]], float]:
    """Test HTTP health response from server."""
    url = f"http://127.0.0.1:{port}/api"
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ServerManager/2.0"})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            latency = (time.time() - start) * 1000
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return True, data, latency
    except Exception:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "ServerManager/2.0"})
            with urllib.request.urlopen(req, timeout=1.5) as response:
                latency = (time.time() - start) * 1000
                if response.status == 200:
                    return True, {"status": "ok"}, latency
        except Exception:
            pass
    return False, None, 0.0


def find_pids_on_port(port: int) -> List[int]:
    """Find all process PIDs actively listening on the target port."""
    pids = []
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        pids.append(int(pid_str))
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(f"lsof -t -i:{port}", shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
        except Exception:
            pass
    return list(set(pids))


def start_server(foreground: bool = False) -> bool:
    """Start the web server in background or foreground."""
    cfg = load_config()
    port = cfg.get("port", 5000)

    # 1. Check if port is already active
    if is_port_in_use(port):
        existing_pids = find_pids_on_port(port)
        stored_pid, _ = get_stored_pid_info()
        pid_info = f" (PID: {stored_pid or (existing_pids[0] if existing_pids else 'unknown')})"
        print(f"{Colors.YELLOW}[!] Server is already running on port {port}{pid_info}!{Colors.RESET}")
        print_server_links(cfg)
        return True

    python_exe = find_best_python()
    print(f"{Colors.CYAN}[*] Using Python: {python_exe}{Colors.RESET}")
    print(f"{Colors.CYAN}[*] Starting Contract Note Parser Server on port {port}...{Colors.RESET}")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = cfg.get("host", "0.0.0.0")

    if foreground:
        print(f"{Colors.GREEN}[+] Launching in foreground (Ctrl+C to stop)...{Colors.RESET}")
        try:
            subprocess.run([python_exe, APP_SCRIPT], env=env, cwd=BASE_DIR)
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[*] Server stopped by user.{Colors.RESET}")
        return True

    # Background spawn
    log_f = open(LOG_FILE, "a", encoding="utf-8")
    log_f.write(f"\n--- SERVER STARTED AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_f.flush()

    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000, CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = 0x08000000 | 0x00000200
        proc = subprocess.Popen(
            [python_exe, APP_SCRIPT],
            env=env,
            cwd=BASE_DIR,
            stdout=log_f,
            stderr=log_f,
            creationflags=flags
        )
    else:
        proc = subprocess.Popen(
            [python_exe, APP_SCRIPT],
            env=env,
            cwd=BASE_DIR,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True
        )

    save_pid(proc.pid)

    # 2. Wait up to 5 seconds for server to start listening
    print(f"{Colors.CYAN}[*] Verifying server health...{Colors.RESET}", end="", flush=True)
    started = False
    for _ in range(20):
        time.sleep(0.25)
        print(".", end="", flush=True)
        if is_port_in_use(port):
            is_healthy, _, latency = check_http_health(port)
            if is_healthy:
                started = True
                break

    print()

    if started:
        print(f"\n{Colors.GREEN}{Colors.BOLD}[OK] SERVER STARTED SUCCESSFULLY!{Colors.RESET}")
        print(f"  * Process ID (PID) : {proc.pid}")
        print(f"  * Log File         : {LOG_FILE}")
        print_server_links(cfg)
        return True
    else:
        print(f"\n{Colors.RED}[!] Server started with PID {proc.pid}, but port {port} is not yet answering.{Colors.RESET}")
        print(f"    Check {LOG_FILE} for any startup traceback.")
        return False


def stop_server() -> bool:
    """Gracefully stop the server process and release port."""
    cfg = load_config()
    port = cfg.get("port", 5000)
    stored_pid, _ = get_stored_pid_info()

    pids_to_kill = set()
    if stored_pid and is_process_alive(stored_pid):
        pids_to_kill.add(stored_pid)

    # Also detect any lingering process on port
    port_pids = find_pids_on_port(port)
    pids_to_kill.update(port_pids)

    if not pids_to_kill:
        print(f"{Colors.YELLOW}[*] No active server process found on port {port}. (Server is already STOPPED){Colors.RESET}")
        remove_pid_file()
        return True

    print(f"{Colors.CYAN}[*] Stopping server process (PIDs: {list(pids_to_kill)})...{Colors.RESET}")

    for pid in pids_to_kill:
        try:
            if sys.platform == "win32":
                subprocess.run(f"taskkill /PID {pid} /T /F", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                if is_process_alive(pid):
                    os.kill(pid, signal.SIGKILL)
        except Exception as e:
            print(f"{Colors.YELLOW}[!] Could not terminate PID {pid}: {e}{Colors.RESET}")

    time.sleep(0.6)
    if is_port_in_use(port):
        print(f"{Colors.RED}[!] Port {port} is still in use! Forcing release...{Colors.RESET}")
        for pid in find_pids_on_port(port):
            if sys.platform == "win32":
                subprocess.run(f"taskkill /PID {pid} /F", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)

    remove_pid_file()

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"--- SERVER STOPPED AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n\n")
    except Exception:
        pass

    print(f"{Colors.GREEN}{Colors.BOLD}[OK] SERVER STOPPED SUCCESSFULLY.{Colors.RESET} Port {port} is now free.")
    return True


def restart_server() -> bool:
    """Restart the server cleanly."""
    print(f"{Colors.HEADER}{Colors.BOLD}=== RESTARTING SERVER ==={Colors.RESET}")
    stop_server()
    time.sleep(1.0)
    return start_server(foreground=False)


def get_status_info() -> Dict[str, Any]:
    """Collect comprehensive status data about the server."""
    cfg = load_config()
    port = cfg.get("port", 5000)
    stored_pid, start_time = get_stored_pid_info()
    port_in_use = is_port_in_use(port)
    active_pids = find_pids_on_port(port)

    pid = stored_pid if (stored_pid and is_process_alive(stored_pid)) else (active_pids[0] if active_pids else None)
    is_alive = bool(pid and is_process_alive(pid))

    is_healthy, health_data, latency = check_http_health(port) if port_in_use else (False, None, 0.0)

    # Server is considered running if port is in use and either healthy or PID alive
    is_running = port_in_use and (is_healthy or is_alive)

    uptime_str = "N/A"
    if is_running and start_time:
        elapsed = int(time.time() - start_time)
        uptime_str = str(timedelta(seconds=elapsed))

    metrics = get_process_metrics(pid) if (pid and is_running) else {}

    return {
        "status": "RUNNING" if is_running else "STOPPED",
        "is_running": is_running,
        "is_healthy": is_healthy,
        "latency_ms": round(latency, 1),
        "pid": pid,
        "port": port,
        "uptime": uptime_str,
        "metrics": metrics,
        "health_data": health_data,
        "local_url": f"http://localhost:{port}",
        "network_url": f"http://{get_local_ip()}:{port}",
        "website_url": cfg.get("website_url", ""),
        "github_url": cfg.get("github_url", "")
    }


def print_server_links(cfg: Dict[str, Any]) -> None:
    """Print formatted local, network, and live website links."""
    port = cfg.get("port", 5000)
    local_url = f"http://localhost:{port}"
    net_url = f"http://{get_local_ip()}:{port}"
    website_url = cfg.get("website_url", "").strip()
    github_url = cfg.get("github_url", "").strip()

    print(f"\n  {Colors.BOLD}Accessible URLs:{Colors.RESET}")
    print(f"  * {Colors.CYAN}Local Web App       :{Colors.RESET} {local_url}")
    print(f"  * {Colors.CYAN}Local Network (LAN) :{Colors.RESET} {net_url}")
    print(f"  * {Colors.CYAN}Interactive API Docs:{Colors.RESET} {local_url}/api/docs")

    if website_url:
        print(f"  * {Colors.GREEN}{Colors.BOLD}Live Website Link   :{Colors.RESET} {Colors.GREEN}{Colors.UNDERLINE}{website_url}{Colors.RESET}")
    else:
        print(f"  * {Colors.YELLOW}Live Website Link   :{Colors.RESET} Not set yet. Run 'python server_manager.py set-url <url>'")

    if github_url:
        print(f"  * {Colors.BLUE}GitHub Repository   :{Colors.RESET} {github_url}")


def print_status() -> None:
    """Display visual status dashboard."""
    info = get_status_info()
    cfg = load_config()

    print()
    print(f"{Colors.BOLD}{'='*64}{Colors.RESET}")
    print(f"  {Colors.HEADER}{Colors.BOLD}CONTRACT NOTE PARSER - SERVER STATUS DASHBOARD{Colors.RESET}")
    print(f"  {Colors.CYAN}Developer: {cfg.get('author_name', 'Arham Begani')} | {cfg.get('project_type', 'Open Source Platform')}{Colors.RESET}")
    print(f"{'='*64}")

    if info["is_running"]:
        health_badge = f"{Colors.GREEN}[HEALTHY ({info['latency_ms']} ms)]{Colors.RESET}" if info["is_healthy"] else f"{Colors.YELLOW}[PORT OPEN / API PROBING]{Colors.RESET}"
        print(f"  Status        : {Colors.GREEN}{Colors.BOLD}[ONLINE - RUNNING]{Colors.RESET} {health_badge}")
        print(f"  Process ID    : {info['pid'] or 'Active on Port'}")
        print(f"  Port Bound    : {info['port']}")
        print(f"  Server Uptime : {info['uptime']}")
        if info["metrics"].get("memory_mb"):
            print(f"  Memory Usage  : {info['metrics']['memory_mb']} MB")
        if info["metrics"].get("cpu_percent") is not None:
            print(f"  CPU Usage     : {info['metrics']['cpu_percent']}%")
    else:
        print(f"  Status        : {Colors.RED}{Colors.BOLD}[OFFLINE - STOPPED]{Colors.RESET}")
        print(f"  Port          : {info['port']} (Free)")
        print(f"  Process ID    : None")

    print(f"{'-'*64}")
    print_server_links(cfg)
    print(f"{'-'*64}")

    print(f"  {Colors.BOLD}Quick Reference for Application Forms / Portfolios:{Colors.RESET}")
    print(f"  1. Live Website Demo : {Colors.GREEN}{cfg.get('website_url', '')}{Colors.RESET}")
    print(f"  2. GitHub Repository : {Colors.BLUE}{cfg.get('github_url', '')}{Colors.RESET}")
    print(f"{'='*64}\n")


def set_website_url(url: Optional[str] = None) -> None:
    """Prompt or set the live public website URL."""
    if not url:
        current = load_config().get("website_url", "")
        print(f"\nCurrent Website Link: {Colors.CYAN}{current or '(None)'}{Colors.RESET}")
        url = input("Enter new live website URL (e.g., https://file-parser-r7b0.onrender.com): ").strip()

    if not url:
        print(f"{Colors.YELLOW}[!] No URL provided. Unchanged.{Colors.RESET}")
        return

    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    update_config_value("website_url", url)
    print(f"\n{Colors.GREEN}{Colors.BOLD}[OK] Live Website Link successfully updated to:{Colors.RESET}")
    print(f"  {Colors.CYAN}{Colors.UNDERLINE}{url}{Colors.RESET}")
    print("This link will now appear in your status dashboard and README.\n")


def set_github_url(url: Optional[str] = None) -> None:
    """Prompt or set the GitHub repository URL."""
    if not url:
        current = load_config().get("github_url", "")
        print(f"\nCurrent GitHub Link: {Colors.CYAN}{current or '(None)'}{Colors.RESET}")
        url = input("Enter GitHub repository URL (e.g., https://github.com/Arham-1313/file_parser): ").strip()

    if not url:
        print(f"{Colors.YELLOW}[!] No URL provided. Unchanged.{Colors.RESET}")
        return

    update_config_value("github_url", url)
    print(f"\n{Colors.GREEN}{Colors.BOLD}[OK] GitHub URL updated to:{Colors.RESET} {Colors.CYAN}{url}{Colors.RESET}\n")


def open_browser() -> None:
    """Open the web interface in the default system browser."""
    cfg = load_config()
    info = get_status_info()
    target_url = info["local_url"]

    if not info["is_running"]:
        print(f"{Colors.YELLOW}[*] Server is not running. Starting server first...{Colors.RESET}")
        start_server()
        time.sleep(1.0)

    print(f"{Colors.CYAN}[*] Opening {target_url} in your default browser...{Colors.RESET}")
    webbrowser.open(target_url)


def show_logs(lines: int = 30) -> None:
    """Display the last N lines of the server log."""
    if not os.path.exists(LOG_FILE):
        print(f"{Colors.YELLOW}[*] No log file found yet at {LOG_FILE}.{Colors.RESET}")
        return
    print(f"\n{Colors.CYAN}{'='*20} RECENT LOGS ({LOG_FILE}) {'='*20}{Colors.RESET}")
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            for l in all_lines[-lines:]:
                print(l, end="")
    except Exception as e:
        print(f"{Colors.RED}[!] Could not read log file: {e}{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}\n")


def generate_tunnel_link() -> None:
    """Guide or automatically generate a free public link using cloudflared, ngrok, or localtunnel."""
    cfg = load_config()
    port = cfg.get("port", 5000)

    print(f"\n{Colors.HEADER}{Colors.BOLD}=== FREE INSTANT LIVE WEBSITE LINK GENERATOR ==={Colors.RESET}")
    print("If you haven't deployed to Render or Railway yet, you can create a FREE instant")
    print("live public HTTPS link from your running local server to put in the recruitment form!\n")

    has_cloudflared = subprocess.run("where cloudflared", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    has_ngrok = subprocess.run("where ngrok", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    has_npx = subprocess.run("where npx", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    print("Detected Tools on your System:")
    print(f"  * cloudflared : {'Available' if has_cloudflared else 'Not found'}")
    print(f"  * ngrok       : {'Available' if has_ngrok else 'Not found'}")
    print(f"  * npx (Node)  : {'Available' if has_npx else 'Not found'}\n")

    print(f"{Colors.BOLD}Quick 1-Line Commands to get a Live Public Link:{Colors.RESET}")
    if has_npx:
        print(f"  1. {Colors.CYAN}npx localtunnel --port {port}{Colors.RESET}")
        print("     -> Gives you an instant URL like: https://cool-server-123.loca.lt\n")
    if has_cloudflared:
        print(f"  2. {Colors.CYAN}cloudflared tunnel --url http://localhost:{port}{Colors.RESET}")
        print("     -> Gives you an instant URL like: https://xyz.trycloudflare.com\n")
    if has_ngrok:
        print(f"  3. {Colors.CYAN}ngrok http {port}{Colors.RESET}")
        print("     -> Gives you an instant URL like: https://xyz.ngrok-free.app\n")

    print(f"{Colors.BOLD}Permanent Free Cloud Deployment Options (Recommended for Recruitment):{Colors.RESET}")
    print("  * Render.com : Free hosting. Push this repository to GitHub, connect on Render, choose Python,")
    print("                 Build Command: pip install -r requirements.txt, Start Command: python app.py")
    print("                 -> Gives you permanent link: https://your-project.onrender.com\n")

    link = input("Have you generated or deployed a link? Enter it here to save it (or press Enter to skip): ").strip()
    if link:
        set_website_url(link)


def interactive_menu() -> None:
    """Interactive console menu for user-friendly operation."""
    while True:
        cfg = load_config()
        info = get_status_info()
        status_color = Colors.GREEN if info["is_running"] else Colors.RED
        status_text = "ONLINE" if info["is_running"] else "OFFLINE"

        print(f"\n{Colors.BOLD}{'='*64}{Colors.RESET}")
        print(f"      {Colors.HEADER}{Colors.BOLD}CONTRACT NOTE PARSER - SERVER CONTROLLER{Colors.RESET}")
        print(f"{'='*64}")
        print(f"  Status       : {status_color}{Colors.BOLD}{status_text}{Colors.RESET} (Port: {info['port']})")
        print(f"  Local Link   : {info['local_url']}")
        print(f"  Website Link : {Colors.CYAN}{cfg.get('website_url') or '(Not configured yet)'}{Colors.RESET}")
        print(f"{'-'*64}")
        print("  [1] Start Server (Background)")
        print("  [2] Stop Server")
        print("  [3] Restart Server")
        print("  [4] Detailed Status & Link Dashboard")
        print("  [5] Set / Update Live Website Link")
        print("  [6] Open Web App in Browser")
        print("  [7] View Recent Server Logs")
        print("  [8] Generate Free Public Web Link (Instant Tunnel Guide)")
        print("  [0] Exit")
        print(f"{'='*64}")

        choice = input(f"{Colors.BOLD}Enter choice [0-8]: {Colors.RESET}").strip()

        if choice == "1":
            start_server(foreground=False)
        elif choice == "2":
            stop_server()
        elif choice == "3":
            restart_server()
        elif choice == "4":
            print_status()
        elif choice == "5":
            set_website_url()
        elif choice == "6":
            open_browser()
        elif choice == "7":
            show_logs(25)
        elif choice == "8":
            generate_tunnel_link()
        elif choice in ("0", "q", "exit"):
            print(f"{Colors.CYAN}Exiting Server Controller. Have a great day!{Colors.RESET}")
            break
        else:
            print(f"{Colors.YELLOW}[!] Invalid option. Please enter a number between 0 and 8.{Colors.RESET}")


def main():
    if len(sys.argv) < 2:
        interactive_menu()
        return

    cmd = sys.argv[1].lower().strip()

    if cmd == "start":
        fg = "--foreground" in sys.argv or "-f" in sys.argv
        start_server(foreground=fg)
    elif cmd == "stop":
        stop_server()
    elif cmd == "restart":
        restart_server()
    elif cmd in ("status", "info"):
        print_status()
    elif cmd in ("set-url", "set-link"):
        url = sys.argv[2] if len(sys.argv) > 2 else None
        set_website_url(url)
    elif cmd in ("set-github", "set-repo"):
        url = sys.argv[2] if len(sys.argv) > 2 else None
        set_github_url(url)
    elif cmd in ("url", "urls", "link", "links"):
        cfg = load_config()
        print_server_links(cfg)
    elif cmd in ("open", "browse"):
        open_browser()
    elif cmd in ("logs", "log"):
        lines = int(sys.argv[2]) if (len(sys.argv) > 2 and sys.argv[2].isdigit()) else 30
        show_logs(lines)
    elif cmd in ("tunnel", "public"):
        generate_tunnel_link()
    elif cmd in ("help", "--help", "-h"):
        print(__doc__)
    else:
        print(f"{Colors.RED}[!] Unknown command: {cmd}{Colors.RESET}")
        print("Available commands: start, stop, restart, status, set-url, url, open, logs, tunnel")
        sys.exit(1)


if __name__ == "__main__":
    main()
