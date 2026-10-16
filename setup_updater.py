import sys
import os
import json
import time
import shutil
import subprocess
import ssl
import urllib.request
import urllib.error
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QCheckBox, QDialog,
    QLineEdit, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon


try:
    import certifi
    ca_bundle = certifi.where()
    if os.path.exists(ca_bundle):
        os.environ["SSL_CERT_FILE"] = ca_bundle
        os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
except Exception:
    pass

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    requests = None


def _make_unverified_ssl_context():
    if hasattr(ssl, "_create_unverified_context"):
        ctx = ssl._create_unverified_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL_CTX = _make_unverified_ssl_context()
ssl._create_default_https_context = _make_unverified_ssl_context


class _UnverifiedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(self.getConnection, req)

    def getConnection(self, host, timeout=300, **kwargs):
        return urllib.request.HTTPSConnection(host, timeout=timeout, context=_SSL_CTX, **kwargs)


_CUSTOM_OPENER = urllib.request.build_opener(
    _UnverifiedHTTPSHandler(context=_SSL_CTX),
    urllib.request.HTTPRedirectHandler()
)
urllib.request.install_opener(_CUSTOM_OPENER)


def _fetch_json_url(url, headers=None, timeout=10):
    headers = headers or {"User-Agent": "RB-LMS-Updater/4.8.7"}
    if requests is not None:
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with _CUSTOM_OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except Exception:
        pass
    curl_path = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
    if os.path.exists(curl_path):
        try:
            hdr_args = []
            for k, v in headers.items():
                hdr_args.extend(["-H", f"{k}: {v}"])
            cmd = [curl_path, "-k", "-L", "-s", "--max-time", str(int(timeout))] + hdr_args + [url]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout + 2)
            if res.returncode == 0 and res.stdout:
                return json.loads(res.stdout.decode("utf-8"))
        except Exception:
            pass
    return None


APP_NAME = "RB LMS Auto Tool"
EXE_NAME = "RB_LMS_Auto_Tool_NoKey.exe"
SETUP_EXE_NAME = "RB_LMS_Setup.exe"
DEFAULT_VERSION = "4.8.7"
DEFAULT_GITHUB_REPO = "beluga1401/rb-lms-auto-tool"

INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RB_LMS_Auto_Tool")
CONFIG_FILE = os.path.join(INSTALL_DIR, "updater_config.json")
LOCAL_VERSION_FILE = os.path.join(INSTALL_DIR, "local_version.json")


def load_updater_config():
    os.makedirs(INSTALL_DIR, exist_ok=True)
    cfg = {
        "github_repo": DEFAULT_GITHUB_REPO,
        "custom_manifest_url": "",
        "github_token": "",
        "create_shortcut": True,
        "auto_launch": True,
    }
    # Check local directory version.json first if present next to setup.exe
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    local_ver_json = os.path.join(base_dir, "version.json")
    if os.path.exists(local_ver_json):
        try:
            with open(local_ver_json, "r", encoding="utf-8") as f:
                vdata = json.load(f)
                if vdata.get("github_repo"):
                    cfg["github_repo"] = vdata["github_repo"]
        except Exception:
            pass

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
                    if cfg.get("github_repo") == "rb-lms-team/rb-lms-auto-tool":
                        cfg["github_repo"] = DEFAULT_GITHUB_REPO
        except Exception:
            pass
    return cfg


def save_updater_config(cfg):
    os.makedirs(INSTALL_DIR, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_installed_version():
    exe_path = os.path.join(INSTALL_DIR, EXE_NAME)
    if not os.path.exists(exe_path):
        return None
    if os.path.exists(LOCAL_VERSION_FILE):
        try:
            with open(LOCAL_VERSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version", DEFAULT_VERSION)
        except Exception:
            pass
    return DEFAULT_VERSION


def save_installed_version(version_str, release_notes=""):
    os.makedirs(INSTALL_DIR, exist_ok=True)
    try:
        with open(LOCAL_VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "version": version_str,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "release_notes": release_notes
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_version_tuple(v_str):
    if not v_str:
        return (0, 0, 0)
    clean = str(v_str).strip().lstrip("vV")
    parts = []
    for p in clean.split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class UpdateCheckWorker(QThread):
    finished_signal = pyqtSignal(dict)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        repo = str(self.config.get("github_repo") or DEFAULT_GITHUB_REPO).strip().strip("/")
        custom_url = str(self.config.get("custom_manifest_url") or "").strip()
        token = str(self.config.get("github_token") or "").strip()

        headers = {
            "User-Agent": "RB-LMS-Updater/4.5",
            "Accept": "application/vnd.github+json"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        result = {
            "online": False,
            "version": DEFAULT_VERSION,
            "download_url": "",
            "notes": "Bản chuẩn Gemini 3.7/3.8 Flash + Tự động Xem lại & Thực hiện lại đề thi 100 điểm.",
            "source": "local",
            "error": ""
        }

        # 1. Check Custom Manifest URL if configured
        if custom_url:
            data = _fetch_json_url(custom_url, headers=headers, timeout=8)
            if data and isinstance(data, dict):
                result["online"] = True
                result["version"] = str(data.get("version") or DEFAULT_VERSION).lstrip("vV")
                result["download_url"] = str(data.get("download_url") or "")
                cl = data.get("changelog")
                if isinstance(cl, list):
                    result["notes"] = " • " + "\n • ".join(str(x) for x in cl)
                elif isinstance(cl, str) and cl:
                    result["notes"] = cl
                result["source"] = "manifest"
                self.finished_signal.emit(result)
                return

        # 2. Check GitHub Releases API (/repos/{owner}/{repo}/releases/latest)
        if repo and "/" in repo:
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            rel = _fetch_json_url(api_url, headers=headers, timeout=8)
            if rel and isinstance(rel, dict):
                tag = str(rel.get("tag_name") or DEFAULT_VERSION).lstrip("vV")
                body = str(rel.get("body") or "").strip()
                assets = rel.get("assets") or []
                dl_url = ""
                for asset in assets:
                    aname = str(asset.get("name") or "")
                    if aname.lower() == EXE_NAME.lower():
                        dl_url = str(asset.get("browser_download_url") or "")
                        break
                if not dl_url:
                    for asset in assets:
                        aname = str(asset.get("name") or "")
                        if aname.lower().endswith(".exe") and "setup" not in aname.lower():
                            dl_url = str(asset.get("browser_download_url") or "")
                            break
                if not dl_url:
                    dl_url = f"https://github.com/{repo}/releases/latest/download/{EXE_NAME}"
                result["online"] = True
                result["version"] = tag or DEFAULT_VERSION
                result["download_url"] = dl_url
                if body:
                    result["notes"] = body[:280]
                result["source"] = "github_release"
                self.finished_signal.emit(result)
                return

            # 3. Fallback: Check raw version.json on main / master branch
            for branch in ("main", "master"):
                raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/version.json"
                data = _fetch_json_url(raw_url, headers=headers, timeout=6)
                if data and isinstance(data, dict):
                    result["online"] = True
                    result["version"] = str(data.get("version") or DEFAULT_VERSION).lstrip("vV")
                    result["download_url"] = str(data.get("download_url") or f"https://github.com/{repo}/releases/latest/download/{EXE_NAME}")
                    cl = data.get("changelog")
                    if isinstance(cl, list):
                        result["notes"] = " • " + "\n • ".join(str(x) for x in cl)
                    elif isinstance(cl, str) and cl:
                        result["notes"] = cl
                    result["source"] = f"github_raw_{branch}"
                    self.finished_signal.emit(result)
                    return

        # 4. Local offline fallback check (if RB_LMS_Auto_Tool_NoKey.exe is alongside Setup)
        for cand_dir in [
            os.path.dirname(os.path.abspath(sys.argv[0])),
            os.getcwd(),
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.getcwd(), "dist")
        ]:
            cand_exe = os.path.join(cand_dir, EXE_NAME)
            if os.path.exists(cand_exe):
                result["download_url"] = f"file://{cand_exe}"
                result["source"] = "local_bundle"
                break

        if not result["download_url"] and repo and "/" in repo:
            result["download_url"] = f"https://github.com/{repo}/releases/latest/download/{EXE_NAME}"

        self.finished_signal.emit(result)


class InstallUpdateWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, download_url, target_version, create_shortcut=True, token=""):
        super().__init__()
        self.download_url = download_url
        self.target_version = target_version
        self.create_shortcut = create_shortcut
        self.token = token

    def _terminate_running_app(self):
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", EXE_NAME],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
                time.sleep(0.6)
            except Exception:
                pass

    def _create_windows_shortcuts(self, target_exe):
        if os.name != "nt":
            return
        try:
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            start_menu_dir = os.path.join(
                os.environ.get("APPDATA", ""),
                r"Microsoft\Windows\Start Menu\Programs"
            )
            shortcut_paths = []
            if os.path.isdir(desktop_dir):
                shortcut_paths.append(os.path.join(desktop_dir, f"{APP_NAME}.lnk"))
            if os.path.isdir(start_menu_dir):
                shortcut_paths.append(os.path.join(start_menu_dir, f"{APP_NAME}.lnk"))

            for lnk_path in shortcut_paths:
                ps_cmd = (
                    f"$ws = New-Object -ComObject WScript.Shell; "
                    f"$s = $ws.CreateShortcut('{lnk_path}'); "
                    f"$s.TargetPath = '{target_exe}'; "
                    f"$s.WorkingDirectory = '{INSTALL_DIR}'; "
                    f"$s.Description = '{APP_NAME} - AI Exam Solver'; "
                    f"$s.Save()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
        except Exception:
            pass

    def run(self):
        try:
            os.makedirs(INSTALL_DIR, exist_ok=True)
            target_exe = os.path.join(INSTALL_DIR, EXE_NAME)
            temp_exe = os.path.join(INSTALL_DIR, EXE_NAME + ".download")

            self.progress_signal.emit(5, "Đang kiểm tra và đóng tiến trình cũ...")
            self._terminate_running_app()

            # Copy setup exe itself into INSTALL_DIR so user can run updater anytime
            try:
                curr_self = os.path.abspath(sys.argv[0])
                dest_setup = os.path.join(INSTALL_DIR, SETUP_EXE_NAME)
                if curr_self.lower().endswith(".exe") and os.path.normcase(curr_self) != os.path.normcase(dest_setup):
                    shutil.copy2(curr_self, dest_setup)
            except Exception:
                pass

            dl_url = str(self.download_url or "").strip()
            local_source = ""
            if dl_url.startswith("file://"):
                local_source = dl_url.replace("file://", "")
            elif not dl_url:
                dl_url = f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/latest/download/{EXE_NAME}"

            # Try downloading from GitHub URL if http/https
            downloaded_ok = False
            if dl_url.startswith("http://") or dl_url.startswith("https://"):
                candidate_urls = [dl_url]
                clean_target_v = str(self.target_version or DEFAULT_VERSION).lstrip("vV")
                fallback_tag_url = f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/download/v{clean_target_v}/{EXE_NAME}"
                fallback_latest_url = f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/latest/download/{EXE_NAME}"
                for u in (fallback_tag_url, fallback_latest_url):
                    if u not in candidate_urls:
                        candidate_urls.append(u)

                last_net_err = None
                for try_url in candidate_urls:
                    # Engine 1: requests (with verify=False, stream=True, auto redirect)
                    if requests is not None:
                        try:
                            headers = {"User-Agent": "RB-LMS-Updater/4.8.7"}
                            if self.token and "api.github.com" in try_url:
                                headers["Authorization"] = f"Bearer {self.token}"
                            with requests.get(try_url, headers=headers, stream=True, verify=False, timeout=60, allow_redirects=True) as resp:
                                if resp.status_code == 200:
                                    total_size = int(resp.headers.get("content-length", 0) or 0)
                                    downloaded = 0
                                    chunk_size = 128 * 1024
                                    t_start = time.time()
                                    with open(temp_exe, "wb") as out_f:
                                        for chunk in resp.iter_content(chunk_size=chunk_size):
                                            if chunk:
                                                out_f.write(chunk)
                                                downloaded += len(chunk)
                                                elapsed = max(0.1, time.time() - t_start)
                                                speed_mb = (downloaded / (1024 * 1024)) / elapsed
                                                if total_size > 0:
                                                    pct = min(92, int(10 + (downloaded / total_size) * 82))
                                                    mb_cur = downloaded / (1024 * 1024)
                                                    mb_tot = total_size / (1024 * 1024)
                                                    self.progress_signal.emit(
                                                        pct,
                                                        f"Đang tải bản cập nhật: {mb_cur:.1f} / {mb_tot:.1f} MB ({speed_mb:.1f} MB/s)..."
                                                    )
                                                else:
                                                    mb_cur = downloaded / (1024 * 1024)
                                                    self.progress_signal.emit(
                                                        50,
                                                        f"Đang tải bản cập nhật: {mb_cur:.1f} MB ({speed_mb:.1f} MB/s)..."
                                                    )
                                    if os.path.exists(temp_exe) and os.path.getsize(temp_exe) > 100 * 1024:
                                        shutil.move(temp_exe, target_exe)
                                        downloaded_ok = True
                                        break
                        except Exception as e_req:
                            last_net_err = e_req
                            if os.path.exists(temp_exe):
                                try:
                                    os.remove(temp_exe)
                                except Exception:
                                    pass

                    # Engine 2: Windows native curl.exe with -k -L
                    if not downloaded_ok:
                        curl_path = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
                        if os.path.exists(curl_path):
                            try:
                                self.progress_signal.emit(15, "Đang tải bản cập nhật qua Curl bảo mật...")
                                cmd = [curl_path, "-k", "-L", "-s", "-S", "-o", temp_exe, try_url]
                                proc = subprocess.Popen(cmd)
                                t_start = time.time()
                                while proc.poll() is None:
                                    time.sleep(0.5)
                                    if os.path.exists(temp_exe):
                                        cur_sz = os.path.getsize(temp_exe)
                                        mb_cur = cur_sz / (1024 * 1024)
                                        elapsed = max(0.1, time.time() - t_start)
                                        speed_mb = mb_cur / elapsed
                                        self.progress_signal.emit(
                                            min(90, int(10 + mb_cur / 2.5)),
                                            f"Đang tải bản cập nhật: {mb_cur:.1f} MB ({speed_mb:.1f} MB/s)..."
                                        )
                                if proc.returncode == 0 and os.path.exists(temp_exe) and os.path.getsize(temp_exe) > 100 * 1024:
                                    shutil.move(temp_exe, target_exe)
                                    downloaded_ok = True
                                    break
                            except Exception as e_curl:
                                last_net_err = e_curl
                                if os.path.exists(temp_exe):
                                    try:
                                        os.remove(temp_exe)
                                    except Exception:
                                        pass

                    # Engine 3: _CUSTOM_OPENER (Universal Unverified Opener)
                    if not downloaded_ok:
                        try:
                            headers = {"User-Agent": "RB-LMS-Updater/4.8.7"}
                            if self.token and "api.github.com" in try_url:
                                headers["Authorization"] = f"Bearer {self.token}"
                            req = urllib.request.Request(try_url, headers=headers)
                            with _CUSTOM_OPENER.open(req, timeout=60) as resp:
                                total_size = int(resp.headers.get("Content-Length", 0) or 0)
                                downloaded = 0
                                chunk_size = 128 * 1024
                                t_start = time.time()
                                with open(temp_exe, "wb") as out_f:
                                    while True:
                                        chunk = resp.read(chunk_size)
                                        if not chunk:
                                            break
                                        out_f.write(chunk)
                                        downloaded += len(chunk)
                                        elapsed = max(0.1, time.time() - t_start)
                                        speed_mb = (downloaded / (1024 * 1024)) / elapsed
                                        if total_size > 0:
                                            pct = min(92, int(10 + (downloaded / total_size) * 82))
                                            mb_cur = downloaded / (1024 * 1024)
                                            mb_tot = total_size / (1024 * 1024)
                                            self.progress_signal.emit(
                                                pct,
                                                f"Đang tải bản cập nhật: {mb_cur:.1f} / {mb_tot:.1f} MB ({speed_mb:.1f} MB/s)..."
                                            )
                                        else:
                                            mb_cur = downloaded / (1024 * 1024)
                                            self.progress_signal.emit(
                                                50,
                                                f"Đang tải bản cập nhật: {mb_cur:.1f} MB ({speed_mb:.1f} MB/s)..."
                                            )
                            if os.path.exists(temp_exe) and os.path.getsize(temp_exe) > 100 * 1024:
                                shutil.move(temp_exe, target_exe)
                                downloaded_ok = True
                                break
                        except Exception as net_err:
                            last_net_err = net_err
                            if os.path.exists(temp_exe):
                                try:
                                    os.remove(temp_exe)
                                except Exception:
                                    pass

                if not downloaded_ok:
                    # Check if local file exists as fallback
                    for cand_dir in [
                        os.path.dirname(os.path.abspath(sys.argv[0])),
                        os.getcwd(),
                        os.path.join(os.path.expanduser("~"), "Downloads"),
                        os.path.join(os.getcwd(), "dist")
                    ]:
                        cand = os.path.join(cand_dir, EXE_NAME)
                        if os.path.exists(cand) and os.path.getsize(cand) > 100 * 1024:
                            local_source = cand
                            break
                    if not local_source:
                        self.finished_signal.emit(False, f"Không thể tải từ GitHub ({last_net_err}). Hãy kiểm tra Repo hoặc kết nối mạng.")
                        return

            if not downloaded_ok:
                if not local_source:
                    for cand_dir in [
                        os.path.dirname(os.path.abspath(sys.argv[0])),
                        os.getcwd(),
                        os.path.join(os.path.expanduser("~"), "Downloads"),
                        os.path.join(os.getcwd(), "dist")
                    ]:
                        cand = os.path.join(cand_dir, EXE_NAME)
                        if os.path.exists(cand) and os.path.getsize(cand) > 100 * 1024:
                            local_source = cand
                            break
                if local_source and os.path.exists(local_source):
                    self.progress_signal.emit(45, "Đang cài đặt gói ứng dụng vào hệ thống...")
                    if os.path.normcase(os.path.abspath(local_source)) != os.path.normcase(os.path.abspath(target_exe)):
                        shutil.copy2(local_source, target_exe)
                    self.progress_signal.emit(85, "Đã sao chép tệp thực thi thành công...")
                elif os.path.exists(target_exe):
                    self.progress_signal.emit(85, "Đã xác nhận tệp cài đặt hợp lệ...")
                else:
                    self.finished_signal.emit(
                        False,
                        f"Chưa tìm thấy {EXE_NAME} trên GitHub Release hoặc trong thư mục hiện tại."
                    )
                    return

            save_installed_version(self.target_version)

            if self.create_shortcut:
                self.progress_signal.emit(94, "Đang tạo lối tắt ngoài màn hình Desktop...")
                self._create_windows_shortcuts(target_exe)

            self.progress_signal.emit(100, f"Hoàn tất cài đặt & cập nhật v{self.target_version}!")
            self.finished_signal.emit(True, target_exe)
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class GitHubPublishWorker(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo, token, version_str):
        super().__init__()
        self.repo = repo.strip().strip("/")
        self.token = token.strip()
        self.version_str = version_str.strip().lstrip("vV") or DEFAULT_VERSION

    def _api_request(self, url, method="GET", payload=None, raw_bytes=None, content_type="application/json", timeout=60):
        headers = {
            "User-Agent": "RB-LMS-Updater/4.5",
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}"
        }
        data = None
        if raw_bytes is not None:
            data = raw_bytes
            headers["Content-Type"] = content_type
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if requests is not None:
            try:
                resp = requests.request(method, url, data=data, headers=headers, timeout=timeout, verify=False)
                if resp.status_code == 404:
                    raise urllib.error.HTTPError(url, 404, "Not Found", resp.headers, None)
                resp.raise_for_status()
                return resp.json() if resp.text else {}
            except urllib.error.HTTPError:
                raise
            except Exception:
                pass

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with _CUSTOM_OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def run(self):
        try:
            if not self.token:
                self.finished_signal.emit(False, "Vui lòng nhập GitHub Personal Access Token (quyền repo) để đẩy bản cập nhật.")
                return
            if "/" not in self.repo:
                self.finished_signal.emit(False, "Định dạng GitHub Repo phải là username/repo-name.")
                return

            owner, repo_name = self.repo.split("/", 1)
            self.progress_signal.emit(f"Đang kiểm tra kho lưu trữ {self.repo}...")

            # 1. Check if repo exists; if 404, create public repo automatically
            try:
                self._api_request(f"https://api.github.com/repos/{self.repo}")
            except urllib.error.HTTPError as he:
                if he.code == 404:
                    self.progress_signal.emit(f"Đang khởi tạo kho lưu trữ Public '{repo_name}' trên GitHub...")
                    self._api_request(
                        "https://api.github.com/user/repos",
                        method="POST",
                        payload={
                            "name": repo_name,
                            "description": "RB LMS Auto Tool - Official Setup & Auto-Updater",
                            "private": False,
                            "auto_init": True
                        }
                    )
                    time.sleep(1.5)
                else:
                    raise

            # 2. Find local RB_LMS_Auto_Tool_NoKey.exe to upload
            exe_to_upload = None
            for cand_dir in [
                os.path.join(os.path.expanduser("~"), "Downloads"),
                os.path.dirname(os.path.abspath(sys.argv[0])),
                os.path.join(os.getcwd(), "dist"),
                os.getcwd(),
                INSTALL_DIR
            ]:
                cand = os.path.join(cand_dir, EXE_NAME)
                if os.path.exists(cand) and os.path.getsize(cand) > 100 * 1024:
                    exe_to_upload = cand
                    break

            if not exe_to_upload:
                self.finished_signal.emit(False, f"Không tìm thấy file {EXE_NAME} trong Downloads hoặc thư mục hiện tại để upload.")
                return

            tag_name = f"v{self.version_str}"
            self.progress_signal.emit(f"Đang tạo bản phát hành (Release {tag_name})...")

            # Check if release tag already exists
            release_data = None
            try:
                release_data = self._api_request(f"https://api.github.com/repos/{self.repo}/releases/tags/{tag_name}")
            except urllib.error.HTTPError as he:
                if he.code != 404:
                    raise

            if not release_data:
                release_data = self._api_request(
                    f"https://api.github.com/repos/{self.repo}/releases",
                    method="POST",
                    payload={
                        "tag_name": tag_name,
                        "name": f"RB LMS Auto Tool {tag_name}",
                        "body": (
                            f"### Cập nhật {APP_NAME} {tag_name}\n"
                            f"- Nâng cấp AI Engine Gemini 3.7/3.8 Flash (Dual-AI Consensus & Deep CoT)\n"
                            f"- Tự động phân tích câu Đúng/Sai ở trang Xem lại và tự động Thực hiện lại đề thi\n"
                            f"- Đồng bộ cập nhật tự động qua 1 file `{SETUP_EXE_NAME}` duy nhất"
                        ),
                        "draft": False,
                        "prerelease": False
                    }
                )

            # Delete old asset with same name if present
            for asset in release_data.get("assets", []):
                if asset.get("name") == EXE_NAME:
                    try:
                        self._api_request(
                            f"https://api.github.com/repos/{self.repo}/releases/assets/{asset['id']}",
                            method="DELETE"
                        )
                    except Exception:
                        pass

            upload_url_tmpl = str(release_data.get("upload_url") or "")
            upload_url = upload_url_tmpl.split("{")[0] + f"?name={EXE_NAME}"

            file_size_mb = os.path.getsize(exe_to_upload) / (1024 * 1024)
            self.progress_signal.emit(f"Đang tải {EXE_NAME} ({file_size_mb:.1f} MB) lên GitHub Release...")
            with open(exe_to_upload, "rb") as f_bin:
                raw_bin = f_bin.read()

            self._api_request(
                upload_url,
                method="POST",
                raw_bytes=raw_bin,
                content_type="application/octet-stream",
                timeout=300
            )

            self.finished_signal.emit(
                True,
                f"Đã phát hành thành công {tag_name} lên https://github.com/{self.repo}/releases/tag/{tag_name}"
            )
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi đẩy lên GitHub: {e}")


class GitHubRepoDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("Cấu Hình & Phát Hành GitHub Cloud")
        self.setFixedSize(450, 320)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 7px 10px;
                color: #f8fafc;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background-color: #0284c7;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        lbl_repo = QLabel("GitHub Repository (định dạng: username/repo):")
        self.inp_repo = QLineEdit(self.config.get("github_repo", DEFAULT_GITHUB_REPO))
        self.inp_repo.setPlaceholderText("Ví dụ: nguyenvana/rb-lms-auto-tool")

        lbl_ver = QLabel("Phiên bản phát hành (khi đẩy bản cập nhật mới lên GitHub):")
        self.inp_ver = QLineEdit(DEFAULT_VERSION)
        self.inp_ver.setPlaceholderText("4.5.0")

        lbl_token = QLabel("GitHub Token (chỉ cần khi muốn bấm nút '☁️ Public Lên GitHub'):")
        self.inp_token = QLineEdit(self.config.get("github_token", ""))
        self.inp_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_token.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx (Fine-grained hoặc Classic repo token)")

        self.lbl_pub_status = QLabel("")
        self.lbl_pub_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
        self.lbl_pub_status.setWordWrap(True)

        layout.addWidget(lbl_repo)
        layout.addWidget(self.inp_repo)
        layout.addWidget(lbl_ver)
        layout.addWidget(self.inp_ver)
        layout.addWidget(lbl_token)
        layout.addWidget(self.inp_token)
        layout.addWidget(self.lbl_pub_status)

        btn_row = QHBoxLayout()
        self.btn_publish = QPushButton("☁️ Public Lên GitHub")
        self.btn_publish.setStyleSheet("background-color: #059669; color: white;")
        self.btn_publish.clicked.connect(self._on_publish)

        btn_cancel = QPushButton("Đóng")
        btn_cancel.setStyleSheet("background-color: #334155; color: #e2e8f0;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("Lưu Cấu Hình")
        btn_save.clicked.connect(self._on_save)

        btn_row.addWidget(self.btn_publish)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _on_publish(self):
        repo = self.inp_repo.text().strip() or DEFAULT_GITHUB_REPO
        token = self.inp_token.text().strip()
        ver = self.inp_ver.text().strip() or DEFAULT_VERSION
        self.config["github_repo"] = repo
        self.config["github_token"] = token
        save_updater_config(self.config)

        self.btn_publish.setEnabled(False)
        self.lbl_pub_status.setText("⏳ Đang kết nối GitHub API để tải bản phát hành lên...")
        self.pub_worker = GitHubPublishWorker(repo, token, ver)
        self.pub_worker.progress_signal.connect(lambda m: self.lbl_pub_status.setText(f"⏳ {m}"))
        self.pub_worker.finished_signal.connect(self._on_publish_done)
        self.pub_worker.start()

    def _on_publish_done(self, ok, msg):
        self.btn_publish.setEnabled(True)
        if ok:
            self.lbl_pub_status.setText(f"✅ {msg}")
            QMessageBox.information(self, "Public GitHub Thành Công", msg)
        else:
            self.lbl_pub_status.setText(f"❌ {msg}")
            QMessageBox.warning(self, "Lỗi Public GitHub", msg)

    def _on_save(self):
        self.config["github_repo"] = self.inp_repo.text().strip() or DEFAULT_GITHUB_REPO
        self.config["github_token"] = self.inp_token.text().strip()
        save_updater_config(self.config)
        self.accept()


class MinimalistSetupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_updater_config()
        self.remote_info = {
            "version": DEFAULT_VERSION,
            "download_url": "",
            "notes": "",
            "online": False
        }
        self.setWindowTitle(f"{APP_NAME} — Setup & Auto-Updater")
        self.setFixedSize(480, 325)
        self._init_ui()
        QTimer.singleShot(150, self.check_for_updates)

    def _init_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b1120;
            }
            QWidget#central {
                background-color: #0b1120;
                color: #f8fafc;
                font-family: 'Segoe UI', sans-serif;
            }
            QFrame#card {
                background-color: #111827;
                border: 1px solid #1e293b;
                border-radius: 12px;
            }
            QLabel#title {
                color: #f8fafc;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #94a3b8;
                font-size: 11.5px;
            }
            QLabel#badgeLocal {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#badgeRemote {
                background-color: #0c4a6e;
                color: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 4px;
                height: 8px;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #10b981);
                border-radius: 4px;
            }
            QCheckBox {
                color: #94a3b8;
                font-size: 11.5px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #1e293b;
            }
            QCheckBox::indicator:checked {
                background-color: #0ea5e9;
                border-color: #0ea5e9;
            }
            QPushButton#primaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #10b981);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#primaryBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #059669);
            }
            QPushButton#primaryBtn:disabled {
                background: #1e293b;
                color: #64748b;
            }
            QPushButton#secondaryBtn {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #334155;
            }
            QPushButton#iconBtn {
                background-color: #111827;
                color: #94a3b8;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#iconBtn:hover {
                color: #f8fafc;
                border-color: #38bdf8;
            }
        """)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Header Row
        header_row = QHBoxLayout()
        header_col = QVBoxLayout()
        header_col.setSpacing(2)

        lbl_title = QLabel("⚡ RB LMS Auto Tool")
        lbl_title.setObjectName("title")
        lbl_sub = QLabel("Trình Cài Đặt & Tự Động Cập Nhật (GitHub Cloud)")
        lbl_sub.setObjectName("subtitle")
        header_col.addWidget(lbl_title)
        header_col.addWidget(lbl_sub)

        header_row.addLayout(header_col)
        header_row.addStretch()

        self.btn_cfg = QPushButton("⚙️ GitHub")
        self.btn_cfg.setObjectName("iconBtn")
        self.btn_cfg.setToolTip("Cấu hình địa chỉ GitHub Repository cập nhật tự động")
        self.btn_cfg.clicked.connect(self.open_github_settings)
        header_row.addWidget(self.btn_cfg)

        root.addLayout(header_row)

        # Version Badges Row
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        self.lbl_local_ver = QLabel("Trên máy: Đang kiểm tra...")
        self.lbl_local_ver.setObjectName("badgeLocal")
        self.lbl_remote_ver = QLabel("Bản mới nhất: Đang kiểm tra...")
        self.lbl_remote_ver.setObjectName("badgeRemote")
        badge_row.addWidget(self.lbl_local_ver)
        badge_row.addWidget(self.lbl_remote_ver)
        badge_row.addStretch()
        root.addLayout(badge_row)

        # Main Card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        self.lbl_status = QLabel("Đang kết nối GitHub kiểm tra bản cập nhật mới nhất...")
        self.lbl_status.setStyleSheet("color: #f1f5f9; font-size: 12.5px; font-weight: 600;")
        self.lbl_status.setWordWrap(True)

        self.lbl_notes = QLabel(f"Thư mục cài đặt: {INSTALL_DIR}")
        self.lbl_notes.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_notes.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        card_layout.addWidget(self.lbl_status)
        card_layout.addWidget(self.lbl_notes)
        card_layout.addSpacing(2)
        card_layout.addWidget(self.progress_bar)
        root.addWidget(card)

        # Options Row
        opt_row = QHBoxLayout()
        self.chk_shortcut = QCheckBox("Tạo lối tắt ngoài Desktop")
        self.chk_shortcut.setChecked(bool(self.config.get("create_shortcut", True)))
        self.chk_autolaunch = QCheckBox("Tự mở ứng dụng sau khi xong")
        self.chk_autolaunch.setChecked(bool(self.config.get("auto_launch", True)))
        opt_row.addWidget(self.chk_shortcut)
        opt_row.addStretch()
        opt_row.addWidget(self.chk_autolaunch)
        root.addLayout(opt_row)

        # Action Buttons Row
        act_row = QHBoxLayout()
        act_row.setSpacing(10)

        self.btn_launch = QPushButton("🚀 Mở App")
        self.btn_launch.setObjectName("secondaryBtn")
        self.btn_launch.clicked.connect(self.launch_installed_app)
        self.btn_launch.setVisible(False)

        self.btn_action = QPushButton("⬇️ Cài Đặt & Cập Nhật Ngay")
        self.btn_action.setObjectName("primaryBtn")
        self.btn_action.clicked.connect(self.start_install_or_update)

        act_row.addWidget(self.btn_launch)
        act_row.addWidget(self.btn_action, stretch=1)
        root.addLayout(act_row)

        self._refresh_local_badge()

    def _refresh_local_badge(self):
        installed_v = get_installed_version()
        if installed_v:
            self.lbl_local_ver.setText(f"Trên máy: v{installed_v}")
            self.btn_launch.setVisible(True)
        else:
            self.lbl_local_ver.setText("Trên máy: Chưa cài đặt")
            self.btn_launch.setVisible(False)

    def open_github_settings(self):
        dlg = GitHubRepoDialog(self, self.config)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config = load_updater_config()
            self.check_for_updates()

    def check_for_updates(self):
        self._refresh_local_badge()
        self.btn_action.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.lbl_status.setText("🔍 Đang kiểm tra phiên bản mới trên GitHub...")
        self.worker_check = UpdateCheckWorker(self.config)
        self.worker_check.finished_signal.connect(self._on_check_finished)
        self.worker_check.start()

    def _on_check_finished(self, info):
        self.remote_info = info
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_action.setEnabled(True)

        installed_v = get_installed_version()
        remote_v = info.get("version", DEFAULT_VERSION)
        self.lbl_remote_ver.setText(f"Bản mới nhất: v{remote_v}")

        notes = info.get("notes") or ""
        if notes:
            first_line = notes.splitlines()[0].strip()
            self.lbl_notes.setText(first_line[:95])

        if not installed_v:
            self.lbl_status.setText(f"Sẵn sàng cài đặt {APP_NAME} (v{remote_v}).")
            self.btn_action.setText(f"⬇️ Cài Đặt Ngay (v{remote_v})")
        elif parse_version_tuple(remote_v) > parse_version_tuple(installed_v):
            self.lbl_status.setText(f"🎉 Phát hiện bản cập nhật mới v{remote_v}! (Bản hiện tại: v{installed_v})")
            self.btn_action.setText(f"⚡ Cập Nhật Lên v{remote_v}")
        else:
            self.lbl_status.setText(f"✅ Bạn đang sử dụng phiên bản mới nhất (v{installed_v}).")
            self.btn_action.setText(f"🔄 Cập Nhật / Cài Đặt Lại (v{remote_v})")

    def start_install_or_update(self):
        self.config["create_shortcut"] = self.chk_shortcut.isChecked()
        self.config["auto_launch"] = self.chk_autolaunch.isChecked()
        save_updater_config(self.config)

        self.btn_action.setEnabled(False)
        self.btn_launch.setEnabled(False)
        self.btn_cfg.setEnabled(False)

        dl_url = self.remote_info.get("download_url", "")
        target_v = self.remote_info.get("version", DEFAULT_VERSION)
        token = self.config.get("github_token", "")

        self.worker_install = InstallUpdateWorker(
            download_url=dl_url,
            target_version=target_v,
            create_shortcut=self.chk_shortcut.isChecked(),
            token=token
        )
        self.worker_install.progress_signal.connect(self._on_install_progress)
        self.worker_install.finished_signal.connect(self._on_install_finished)
        self.worker_install.start()

    def _on_install_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_install_finished(self, ok, result_msg):
        self.btn_action.setEnabled(True)
        self.btn_launch.setEnabled(True)
        self.btn_cfg.setEnabled(True)
        self._refresh_local_badge()

        if ok:
            self.progress_bar.setValue(100)
            self.lbl_status.setText("✅ Đã cài đặt & cập nhật thành công!")
            self.btn_action.setText("🔄 Kiểm Tra & Cập Nhật Lại")
            if self.chk_autolaunch.isChecked():
                QTimer.singleShot(500, self.launch_installed_app)
        else:
            self.progress_bar.setValue(0)
            self.lbl_status.setText(f"❌ Lỗi: {result_msg[:80]}")
            QMessageBox.warning(self, "Thông báo cập nhật", result_msg)

    def launch_installed_app(self):
        target_exe = os.path.join(INSTALL_DIR, EXE_NAME)
        if os.path.exists(target_exe):
            try:
                subprocess.Popen([target_exe], cwd=INSTALL_DIR)
                self.close()
            except Exception as e:
                QMessageBox.warning(self, "Lỗi mở ứng dụng", f"Không thể khởi chạy {EXE_NAME}:\n{e}")
        else:
            QMessageBox.warning(self, "Chưa cài đặt", "Ứng dụng chưa được cài đặt. Vui lòng bấm 'Cài Đặt Ngay'.")


def main():
    app = QApplication(sys.argv)
    win = MinimalistSetupWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
