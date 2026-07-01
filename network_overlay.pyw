#!/usr/bin/env python3
"""
Network Status Overlay — 屏幕网络状态悬浮窗
  - 优先显示 WiFi SSID，无 WiFi 时显示以太网/其他连接状态
  - 解锁后可拖动，锁定后鼠标穿透（不干扰游戏 / 全屏应用）
  - 右键菜单切换锁定/解锁、透明度、字号、刷新间隔
  - 位置和状态自动保存到同目录 overlay_config.json
  - 滚轮调整透明度
  - 完全静默，无任何控制台窗口闪现

使用方式:
  - 双击 .pyw 文件直接启动（无命令行窗口）
  - 或运行 启动悬浮窗.bat / 启动悬浮窗(静默).vbs
  - 右键悬浮窗打开设置菜单
  - 解锁状态（🔓）：左键拖动移动位置
  - 锁定状态（🔒）：鼠标穿透，不干扰下层应用
  - 在任务管理器中显示为 "NetworkOverlay" 进程
"""

import tkinter as tk
import json
import os
import re
import subprocess
import sys
import ctypes
import ctypes.wintypes
import atexit
import threading
import winreg

# ── 路径 ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "overlay_config.json")
LOCK_PATH = os.path.join(SCRIPT_DIR, ".overlay.lock")
APP_NAME = "NetworkOverlay"

# 隐藏子进程窗口的 creationflags (Python 3.7+)
try:
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW  # 0x08000000
except AttributeError:
    CREATE_NO_WINDOW = 0x08000000

# STARTUPINFO 配合 SW_HIDE 彻底隐藏子进程窗口，防止任务栏图标闪烁
_startupinfo = subprocess.STARTUPINFO()
_startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
_startupinfo.wShowWindow = subprocess.SW_HIDE


# ── 单实例锁 ──────────────────────────────────────────
# 使用 Windows Mutex 作为主要的单实例检测机制。
# Mutex 对象在进程退出（包括崩溃、断电、关机）时由 OS 自动释放，
# 彻底避免重启后 PID 复用导致误判的问题。
# 保留 .overlay.lock 文件用于错误提示信息兼容。

_MUTEX_HANDLE = None


def acquire_lock():
    """使用 Windows Mutex 防止多实例运行。返回 True 表示成功获取锁。"""
    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    mutex_name = "Global\\NetworkOverlay_SingleInstance"

    # 创建命名 Mutex；如果已存在则打开它
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, mutex_name)
    last_error = kernel32.GetLastError()

    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        # Mutex 已被另一个实例持有 → 已有实例在运行
        if _MUTEX_HANDLE:
            kernel32.CloseHandle(_MUTEX_HANDLE)
            _MUTEX_HANDLE = None
        # 清理可能残留的旧锁文件（重启后 PID 复用场景）
        _cleanup_stale_lock()
        return False

    if not _MUTEX_HANDLE:
        # Mutex 创建失败，回退到文件锁
        return _acquire_file_lock()

    # Mutex 获取成功，更新锁文件（用于错误提示中的 PID 信息）
    _cleanup_stale_lock()
    try:
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    return True


def _acquire_file_lock():
    """文件锁回退方案（仅在 Mutex 不可用时使用）"""
    try:
        if os.path.exists(LOCK_PATH):
            try:
                with open(LOCK_PATH, "r") as f:
                    old_pid = int(f.read().strip())
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, old_pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return False
            except (ValueError, OSError):
                pass
            try:
                os.remove(LOCK_PATH)
            except OSError:
                pass

        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True


def _cleanup_stale_lock():
    """清理残留的锁文件"""
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


def release_lock():
    """释放 Mutex 和锁文件"""
    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    if _MUTEX_HANDLE:
        try:
            kernel32.ReleaseMutex(_MUTEX_HANDLE)
            kernel32.CloseHandle(_MUTEX_HANDLE)
        except Exception:
            pass
        _MUTEX_HANDLE = None
    _cleanup_stale_lock()


atexit.register(release_lock)

# ── Windows API 常量和函数 ────────────────────────────
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.windll.user32

SetWindowLongPtrW = user32.SetWindowLongPtrW
SetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
SetWindowLongPtrW.restype = ctypes.c_longlong

GetWindowLongPtrW = user32.GetWindowLongPtrW
GetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
GetWindowLongPtrW.restype = ctypes.c_longlong

SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
SetWindowPos.restype = ctypes.c_int

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


def get_hwnd(tk_root):
    """可靠地获取 tk 窗口的 HWND"""
    try:
        hwnd = tk_root.winfo_id()
        if hwnd and hwnd != 0:
            return hwnd
    except Exception:
        pass
    try:
        frame_str = tk_root.frame()
        if frame_str:
            return int(frame_str, 16)
    except Exception:
        pass
    return 0


# ── 辅助：解码子进程输出 ──────────────────────────────
def _decode_output(raw_bytes):
    """尝试多种编码解码子进程输出（UTF-8 优先，GBK 回退）"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="replace")


# ── 持久化后台网络检测 ────────────────────────────────
# 使用单个长期存活的 PowerShell 进程，通过管道持续读取网络状态，
# 避免每次刷新都创建新进程导致任务栏图标闪烁。

_NETWORK_WORKER = None
_NETWORK_CACHE = ("检测中...", False, None)  # (display_text, is_wifi, ssid)
_NETWORK_LOCK = threading.Lock()
_NETWORK_RUNNING = True

_NETWORK_PS_SCRIPT = r'''
# 强制使用 UTF-8 编码输出，确保中文 SSID 不乱码
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
# 设置控制台代码页为 UTF-8，让 netsh 等外部命令也以 UTF-8 输出
& chcp 65001 > $null 2>&1

while ($true) {
    $result = @{Type="none"; Name=""; Signal=0}

    # 1. WiFi (netsh)
    $netsh = netsh wlan show interfaces 2>$null | Out-String
    if ($LASTEXITCODE -eq 0) {
        $ssidMatch = [regex]::Match($netsh, 'SSID\s*:\s*(.+)')
        $sigMatch = [regex]::Match($netsh, '(\d+)\s*%')
        if ($ssidMatch.Success) {
            $ssid = $ssidMatch.Groups[1].Value.Trim()
        } else { $ssid = $null }
        if ($sigMatch.Success) {
            $sig = [int]$sigMatch.Groups[1].Value
        } else { $sig = 0 }
        # SSID 非空 且 信号 > 0 → WiFi 已连接
        if ($ssid -and $sig -gt 0) {
            $result.Type = "wifi"
            $result.Name = $ssid
            $result.Signal = $sig
        }
    }

    # 2. Fallback: 其他网络适配器
    if ($result.Type -eq "none") {
        try {
            $adapter = Get-NetAdapter -ErrorAction Stop | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty Name
            if ($adapter) {
                $result.Type = "other"
                $result.Name = $adapter
            }
        } catch {}
    }

    # 3. 最后尝试：默认路由
    if ($result.Type -eq "none") {
        try {
            $iface = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Get-NetIPInterface | Where-Object ConnectionState -eq 'Connected').InterfaceAlias | Select-Object -First 1
            if ($iface) {
                $result.Type = "other"
                $result.Name = $iface
            }
        } catch {}
    }

    $json = ConvertTo-Json -Compress $result
    Write-Output ("NETJSON:" + $json)
    Start-Sleep -Seconds 3
}
'''


def _start_network_worker():
    """启动持久化 PowerShell 后台进程，在独立线程中读取输出并缓存结果。"""
    global _NETWORK_WORKER
    try:
        _NETWORK_WORKER = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-Command", _NETWORK_PS_SCRIPT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo,
        )
    except Exception:
        _NETWORK_WORKER = None
        return

    def _reader():
        global _NETWORK_CACHE, _NETWORK_RUNNING, _NETWORK_WORKER
        try:
            for line in iter(_NETWORK_WORKER.stdout.readline, b''):
                if not _NETWORK_RUNNING:
                    break
                try:
                    decoded = _decode_output(line).strip()
                    if decoded.startswith("NETJSON:"):
                        data = json.loads(decoded[8:])
                        display_text, is_wifi, ssid = _parse_network_data(data)
                        with _NETWORK_LOCK:
                            _NETWORK_CACHE = (display_text, is_wifi, ssid)
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            # worker 进程意外退出时标记为 None，下次刷新会自动重启
            _NETWORK_WORKER = None

    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def _parse_network_data(data):
    """将 PowerShell 返回的 JSON 数据解析为 (display_text, is_wifi, ssid)。"""
    net_type = data.get("Type", "none")
    name = data.get("Name", "")
    signal = data.get("Signal", 0)

    if net_type == "wifi" and name:
        if signal and signal > 0:
            if signal >= 80:
                bars = "▂▄▆█"
            elif signal >= 60:
                bars = "▂▄▆▁"
            elif signal >= 40:
                bars = "▂▄▁▁"
            elif signal >= 20:
                bars = "▂▁▁▁"
            else:
                bars = "▁▁▁▁"
        else:
            bars = "▂▄▆█"
        return f"📶 {bars}  {name}", True, name

    if net_type == "other" and name:
        if "以太网" in name or "Ethernet" in name:
            return f"🔌 {name}", False, name
        else:
            return f"🌐 {name}", False, name

    return "❌ 无网络连接", False, None


def get_network_status():
    """
    获取缓存的网络状态。不再每次创建子进程，只读取后台 worker 的最新结果。
    如果 worker 未启动或已退出，自动重启。
    """
    global _NETWORK_WORKER
    if _NETWORK_WORKER is None or _NETWORK_WORKER.poll() is not None:
        _start_network_worker()
    with _NETWORK_LOCK:
        return _NETWORK_CACHE


def _stop_network_worker():
    """停止后台网络检测进程。"""
    global _NETWORK_RUNNING, _NETWORK_WORKER
    _NETWORK_RUNNING = False
    try:
        if _NETWORK_WORKER and _NETWORK_WORKER.poll() is None:
            _NETWORK_WORKER.terminate()
    except Exception:
        pass


atexit.register(_stop_network_worker)


# ── 配置管理 ──────────────────────────────────────────
def load_config():
    defaults = {
        "x": None,
        "y": None,
        "locked": False,
        "opacity": 0.75,
        "font_size": 11,
        "refresh_interval": 5,
        "auto_start": False,
        "wifi_categories": {},  # SSID → "green" | "red"，新 WiFi 默认 "red"
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
    except Exception:
        pass
    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def lock_icon(locked):
    return "🔒" if locked else "🔓"


# ── 开机自启管理 ──────────────────────────────────────
AUTO_START_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_auto_start_cmd():
    """生成开机自启的命令行（当前 pythonw + 本脚本的绝对路径）"""
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def set_auto_start(enable):
    """设置或取消开机自启（当前用户 HKCU，无需管理员权限）"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTO_START_REG_KEY,
                             0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_auto_start_cmd())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def is_auto_start_enabled():
    """检查当前是否已设置开机自启"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTO_START_REG_KEY,
                             0, winreg.KEY_READ)
        try:
            val, regtype = winreg.QueryValueEx(key, APP_NAME)
            return val == _get_auto_start_cmd()
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


# ── 主窗口类 ──────────────────────────────────────────
class NetworkOverlay:
    def __init__(self):
        self.config = load_config()
        # 启动时同步实际注册表状态到配置（防止手动删除注册表后配置残留）
        actual = is_auto_start_enabled()
        if self.config.get("auto_start") != actual:
            self.config["auto_start"] = actual
            save_config(self.config)
        self._exiting = False
        self._mgmt_window = None  # WiFi 管理窗口引用

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.geometry("260x44")

        # 使用纯色背景（不再用 transparentcolor，避免与扩展样式冲突）
        self.bg_color = "#1a1a2e"
        self.inner_bg = "#16213e"
        self.root.configure(bg=self.bg_color)
        self.root.wm_attributes("-topmost", 1)
        self.root.wm_attributes("-alpha", self.config["opacity"])

        self._drag_data = {"x": 0, "y": 0, "dragging": False}
        self.network_text = ""

        self._build_ui()
        self._set_initial_position()
        self._build_context_menu()
        self._bind_events()
        self._apply_window_ex_styles()

        self._refresh_network()
        self.root.deiconify()

        if self.config["locked"]:
            self._set_click_through(True)
            self.lock_btn_text.set(lock_icon(True))
            self.lock_btn.configure(fg="#e94560")

    # ── UI 构建 ──────────────────────────────────
    def _build_ui(self):
        self.main_frame = tk.Frame(self.root, bg=self.bg_color, highlightthickness=0, bd=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.inner_frame = tk.Frame(
            self.main_frame, bg=self.inner_bg,
            highlightthickness=1, highlightbackground="#0f3460",
            highlightcolor="#0f3460", bd=0,
        )
        self.inner_frame.pack(fill=tk.BOTH, expand=True)

        self.net_label = tk.Label(
            self.inner_frame, text="检测中...",
            fg="#e0e0e0", bg=self.inner_bg,
            font=("Microsoft YaHei UI", self.config["font_size"], "bold"),
            anchor="w", padx=8, pady=2,
        )
        self.net_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lock_btn_text = tk.StringVar(value=lock_icon(self.config["locked"]))
        self.lock_btn = tk.Label(
            self.inner_frame, textvariable=self.lock_btn_text,
            fg="#a0a0a0", bg=self.inner_bg,
            font=("Segoe UI Symbol", 12), padx=6, pady=2, cursor="hand2",
        )
        self.lock_btn.pack(side=tk.RIGHT)

        self.close_btn = tk.Label(
            self.inner_frame, text="✕",
            fg="#a0a0a0", bg=self.inner_bg,
            font=("Segoe UI Symbol", 10), padx=4, pady=2, cursor="hand2",
        )
        self.close_btn.pack(side=tk.RIGHT)

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei UI", 9))
        self.context_menu.add_command(label="🔓 切换锁定 / 解锁", command=self._toggle_lock)
        self.context_menu.add_separator()

        opacity_menu = tk.Menu(self.context_menu, tearoff=0, font=("Microsoft YaHei UI", 9))
        for val, label in [(0.5, "50%"), (0.65, "65%"), (0.75, "75% (默认)"),
                           (0.85, "85%"), (0.95, "95%")]:
            opacity_menu.add_command(label=label, command=lambda v=val: self._set_opacity(v))
        self.context_menu.add_cascade(label="🔅 透明度", menu=opacity_menu)

        font_menu = tk.Menu(self.context_menu, tearoff=0, font=("Microsoft YaHei UI", 9))
        for size in [9, 10, 11, 12, 14, 16]:
            font_menu.add_command(label=f"{size}px",
                                  command=lambda s=size: self._set_font_size(s))
        self.context_menu.add_cascade(label="🔤 字号", menu=font_menu)

        refresh_menu = tk.Menu(self.context_menu, tearoff=0, font=("Microsoft YaHei UI", 9))
        for sec in [3, 5, 10, 15, 30]:
            refresh_menu.add_command(label=f"{sec} 秒",
                                     command=lambda s=sec: self._set_refresh_interval(s))
        self.context_menu.add_cascade(label="⏱ 刷新间隔", menu=refresh_menu)

        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 手动刷新", command=self._refresh_network)
        self.context_menu.add_command(label="📋 管理 WiFi 分类", command=self._open_wifi_manager)
        self.context_menu.add_command(
            label="☑ 开机自动启动" if self.config.get("auto_start") else "☐ 开机自动启动",
            command=self._toggle_auto_start
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📍 重置位置到右上角", command=self._reset_position)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 退出", command=self._quit)

    # ── 事件绑定 ──────────────────────────────────
    def _bind_events(self):
        for widget in [self.inner_frame, self.net_label]:
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)

        for widget in [self.inner_frame, self.net_label, self.lock_btn]:
            widget.bind("<Button-3>", self._show_context_menu)

        self.lock_btn.bind("<Button-1>", lambda e: self._toggle_lock())
        self.close_btn.bind("<Button-1>", lambda e: self._quit())

        self.inner_frame.bind("<MouseWheel>", self._on_scroll)
        self.net_label.bind("<MouseWheel>", self._on_scroll)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    # ── Windows API ──────────────────────────────
    def _apply_window_ex_styles(self):
        """设置窗口为置顶工具窗口（不在任务栏显示），不使用 WS_EX_LAYERED 避免冲突"""
        self.root.update_idletasks()
        hwnd = get_hwnd(self.root)
        if not hwnd:
            return
        try:
            ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            new_style = (ex_style | WS_EX_TOPMOST |
                         WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass

    def _set_click_through(self, enable):
        """设置鼠标穿透（点击直达下层窗口）"""
        self.root.update_idletasks()
        hwnd = get_hwnd(self.root)
        if not hwnd:
            return
        try:
            ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if enable:
                new_style = ex_style | WS_EX_TRANSPARENT
            else:
                new_style = ex_style & ~WS_EX_TRANSPARENT
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass

    # ── 位置 ──────────────────────────────────────
    def _set_initial_position(self):
        screen_w = self.root.winfo_screenwidth()
        x = self.config.get("x")
        y = self.config.get("y")
        if x is not None and y is not None:
            x = max(0, min(x, screen_w - 260))
            y = max(0, min(y, 200))
        else:
            x = screen_w - 280
            y = 20
        self.root.geometry(f"+{x}+{y}")

    def _save_position(self):
        try:
            self.config["x"] = self.root.winfo_x()
            self.config["y"] = self.root.winfo_y()
            save_config(self.config)
        except Exception:
            pass

    def _reset_position(self):
        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"+{screen_w - 280}+20")
        self._save_position()

    # ── 拖动事件 ─────────────────────────────────
    def _on_drag_start(self, event):
        if self.config["locked"]:
            return
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._drag_data["dragging"] = True

    def _on_drag_motion(self, event):
        if not self._drag_data["dragging"] or self.config["locked"]:
            return
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        new_x = self.root.winfo_x() + dx
        new_y = self.root.winfo_y() + dy
        self.root.geometry(f"+{new_x}+{new_y}")

    def _on_drag_end(self, event):
        self._drag_data["dragging"] = False
        self._save_position()

    def _on_scroll(self, event):
        delta = 0.03 if event.delta > 0 else -0.03
        new_val = round(self.config["opacity"] + delta, 2)
        self._set_opacity(max(0.2, min(1.0, new_val)))

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # ── 功能 ─────────────────────────────────────
    def _toggle_lock(self):
        self.config["locked"] = not self.config["locked"]
        self.lock_btn_text.set(lock_icon(self.config["locked"]))
        if self.config["locked"]:
            self._set_click_through(True)
            self.lock_btn.configure(fg="#e94560")
        else:
            self._set_click_through(False)
            self.lock_btn.configure(fg="#a0a0a0")
        save_config(self.config)

    def _set_opacity(self, val):
        self.config["opacity"] = val
        self.root.wm_attributes("-alpha", val)
        save_config(self.config)

    def _set_font_size(self, size):
        self.config["font_size"] = size
        self.net_label.configure(font=("Microsoft YaHei UI", size, "bold"))
        save_config(self.config)

    def _set_refresh_interval(self, sec):
        self.config["refresh_interval"] = sec
        save_config(self.config)

    def _toggle_auto_start(self):
        """切换开机自启状态"""
        new_state = not self.config.get("auto_start", False)
        set_auto_start(new_state)
        self.config["auto_start"] = new_state
        save_config(self.config)
        self._build_context_menu()  # 重建菜单以更新 ☐/☑ 标识

    def _refresh_network(self):
        """刷新网络状态显示"""
        if self._exiting:
            return
        try:
            text, is_wifi, ssid = get_network_status()
            if text != self.network_text:
                self.network_text = text
                self.net_label.configure(text=text)

            # WiFi 分类颜色（始终检查，因分类可能在管理窗口中变更）
            if is_wifi and ssid:
                categories = self.config.setdefault("wifi_categories", {})
                if ssid not in categories:
                    # 首次连接 → 红色
                    categories[ssid] = "red"
                    save_config(self.config)
                if categories.get(ssid) == "green":
                    self.net_label.configure(fg="#00e676")  # 绿色类
                else:
                    self.net_label.configure(fg="#ff5252")  # 红色类
            else:
                self.net_label.configure(fg="#ff5252")  # 非 WiFi → 红色
        except Exception:
            pass  # 静默处理刷新错误，不影响定时器继续
        interval_ms = self.config.get("refresh_interval", 5) * 1000
        self.root.after(interval_ms, self._refresh_network)

    # ── WiFi 分类管理 ──────────────────────────
    def _open_wifi_manager(self):
        """打开 WiFi 分类管理窗口"""
        # 已有窗口则提到前面
        if self._mgmt_window is not None:
            try:
                self._mgmt_window.lift()
                self._mgmt_window.focus_force()
                return
            except tk.TclError:
                self._mgmt_window = None

        win = tk.Toplevel(self.root)
        self._mgmt_window = win
        win.title("WiFi 分类管理")
        win.configure(bg="#1a1a2e")
        win.resizable(True, True)
        win.minsize(320, 240)
        win.geometry("380x400")
        # 居中于屏幕
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = 380
        wh = 400
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        # 窗口关闭时清理引用
        def _on_mgmt_close():
            self._mgmt_window = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_mgmt_close)

        # ── 标题 ──
        header = tk.Label(
            win, text="WiFi 分类管理",
            font=("Microsoft YaHei UI", 13, "bold"),
            fg="#e0e0e0", bg="#1a1a2e", pady=10,
        )
        header.pack(fill=tk.X)

        hint = tk.Label(
            win, text="✔ = 绿色类　　☐ = 红色类（默认）",
            font=("Microsoft YaHei UI", 9),
            fg="#888", bg="#1a1a2e", pady=4,
        )
        hint.pack(fill=tk.X)

        # ── 当前连接 ──
        _, _, cur_ssid = get_network_status()
        if cur_ssid:
            cur_label = tk.Label(
                win,
                text=f"当前连接：{cur_ssid}",
                font=("Microsoft YaHei UI", 10),
                fg="#73c2fb", bg="#1a1a2e", pady=2,
            )
        else:
            cur_label = tk.Label(
                win,
                text="当前无 WiFi 连接",
                font=("Microsoft YaHei UI", 10),
                fg="#888", bg="#1a1a2e", pady=2,
            )
        cur_label.pack(fill=tk.X)

        # 分隔线
        sep = tk.Frame(win, height=1, bg="#0f3460")
        sep.pack(fill=tk.X, padx=16, pady=6)

        # ── 可滚动的 SSID 列表 ──
        canvas = tk.Canvas(win, bg="#16213e", highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        list_frame = tk.Frame(canvas, bg="#16213e")

        list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(16, 0), pady=4)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 16), pady=4)

        # ── 为每个 SSID 创建 Checkbutton ──
        categories = self.config.setdefault("wifi_categories", {})
        ssid_vars = {}  # SSID → tk.BooleanVar

        def _toggle_ssid(ssid):
            """勾选/取消勾选时立即保存并刷新颜色"""
            if ssid_vars[ssid].get():
                categories[ssid] = "green"
            else:
                categories[ssid] = "red"
            save_config(self.config)
            self._refresh_network()

        # 按字母排序显示
        sorted_ssids = sorted(categories.keys(), key=str.lower)
        if not sorted_ssids:
            empty_label = tk.Label(
                list_frame,
                text="暂无连接记录\n连接 WiFi 后会自动出现在这里",
                font=("Microsoft YaHei UI", 10),
                fg="#666", bg="#16213e", pady=20,
                justify=tk.CENTER,
            )
            empty_label.pack(fill=tk.X)
        else:
            for ssid in sorted_ssids:
                is_green = categories.get(ssid) == "green"
                var = tk.BooleanVar(value=is_green)
                ssid_vars[ssid] = var

                # 标记当前连接
                is_current = (ssid == cur_ssid)

                row = tk.Frame(list_frame, bg="#16213e", pady=1)
                row.pack(fill=tk.X, padx=4)

                cb = tk.Checkbutton(
                    row,
                    text=ssid,
                    variable=var,
                    command=lambda s=ssid: _toggle_ssid(s),
                    font=("Microsoft YaHei UI", 10, "bold" if is_current else "normal"),
                    fg="#73c2fb" if is_current else "#e0e0e0",
                    bg="#16213e",
                    selectcolor="#16213e",
                    activebackground="#1a1a2e",
                    activeforeground="#73c2fb",
                    padx=4,
                    anchor="w",
                )
                cb.pack(side=tk.LEFT, fill=tk.X, expand=True)

                # 当前连接标记
                if is_current:
                    dot = tk.Label(
                        row,
                        text="⬤",
                        font=("Segoe UI", 8),
                        fg="#00e676", bg="#16213e",
                        padx=4,
                    )
                    dot.pack(side=tk.RIGHT)

        # ── 底部按钮 ──
        btn_frame = tk.Frame(win, bg="#1a1a2e", pady=10)
        btn_frame.pack(fill=tk.X, padx=16)

        close_btn = tk.Label(
            btn_frame,
            text="关 闭",
            font=("Microsoft YaHei UI", 10, "bold"),
            fg="#e0e0e0", bg="#0f3460",
            padx=20, pady=4, cursor="hand2",
        )
        close_btn.pack()
        close_btn.bind("<Button-1>", lambda e: _on_mgmt_close())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(bg="#1a5276"))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(bg="#0f3460"))

        # 按 Escape 关闭
        win.bind("<Escape>", lambda e: _on_mgmt_close())

    def _quit(self):
        """退出程序 - 保存配置、释放锁、停止后台进程、销毁窗口"""
        self._exiting = True
        self._save_position()
        # 关闭 WiFi 管理窗口
        if self._mgmt_window is not None:
            try:
                self._mgmt_window.destroy()
            except Exception:
                pass
            self._mgmt_window = None
        _stop_network_worker()
        release_lock()
        try:
            self.root.destroy()
        except Exception:
            pass
        # 使用 os._exit 确保进程完全终止，不会卡住
        os._exit(0)

    def run(self):
        self.root.mainloop()


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    # 单实例检测（使用锁文件，比 FindWindowW 更可靠）
    if not acquire_lock():
        try:
            user32.MessageBoxW(0,
                               "网络悬浮窗已在运行中。\n"
                               "请查看屏幕右上角，或右键点击锁图标退出已有实例。\n"
                               "如果在任务管理器中结束 NetworkOverlay 进程后仍无法启动，\n"
                               "请删除程序目录下的 .overlay.lock 文件。",
                               APP_NAME, 0x40)
        except Exception:
            pass
        sys.exit(0)

    app = NetworkOverlay()
    app.run()
