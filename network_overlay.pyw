#!/usr/bin/env python3
"""
Network Status Overlay — 屏幕网络状态悬浮窗
  - 优先显示 WiFi SSID，无 WiFi 时显示以太网/其他连接状态
  - 解锁后可拖动，锁定后其余区域鼠标穿透（不干扰游戏 / 全屏应用），
    锁图标仍可点击解锁
  - 系统托盘图标：左键切换锁定，右键弹出菜单（锁定穿透时的备用操作入口）
  - 右键菜单切换锁定/解锁、透明度、字号、刷新间隔
  - 位置和状态自动保存到同目录 overlay_config.json
  - 滚轮调整透明度
  - 完全静默，无任何控制台窗口闪现

使用方式:
  - 双击 .pyw 文件直接启动（无命令行窗口）
  - 或运行 启动悬浮窗.bat / 启动悬浮窗(静默).vbs
  - 右键悬浮窗打开设置菜单
  - 解锁状态（🔓）：左键拖动移动位置
  - 锁定状态（🔒）：其余区域鼠标穿透、不会误点，仅锁图标可再次点击解锁；
    也可用系统托盘图标左键切换，右键打开菜单
  - 在任务管理器中显示为 "NetworkOverlay" 进程
"""

import tkinter as tk
import tkinter.font as tkfont
import json
import os
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
GWLP_WNDPROC = -4
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020

# 命中测试（WM_NCHITTEST）返回值，用于锁定时的选择性穿透
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTNOWHERE = 0
HTTRANSPARENT = -1

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

GetAncestor = user32.GetAncestor
GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
GetAncestor.restype = ctypes.wintypes.HWND

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020

# ── 64 位函数签名（防止 ctypes 默认 c_int 截断指针/句柄/地址）────────
CallWindowProcW = user32.CallWindowProcW
CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.wintypes.HWND,
                            ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
CallWindowProcW.restype = ctypes.c_longlong

user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
user32.CreateIconIndirect.restype = ctypes.c_void_p
user32.DestroyIcon.argtypes = [ctypes.c_void_p]
user32.GetCursorPos.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint,
                                ctypes.c_size_t, ctypes.c_ssize_t]

_gdi32 = ctypes.windll.gdi32
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
_gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int,
                                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
_gdi32.CreateBitmap.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.CreateSolidBrush.argtypes = [ctypes.c_ulong]
_gdi32.CreateSolidBrush.restype = ctypes.c_void_p
_gdi32.Rectangle.argtypes = [ctypes.c_void_p,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.Ellipse.argtypes = [ctypes.c_void_p,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


def get_hwnd(tk_root):
    """可靠地获取 tk 窗口的『真实顶层』HWND。

    注意：winfo_id() 返回的是 Tk 内部创建的 TkChild，并不是操作系统
    命中的那个顶层窗口；扩展样式、WM_NCHITTEST 命中测试、置顶等窗口级
    操作都必须作用于真正的顶层 TkTopLevel（winfo_id 的根祖先），否则
    WS_EX_TRANSPARENT / 命中测试等都不会真正生效。"""
    try:
        hwnd = tk_root.winfo_id()
        if hwnd and hwnd != 0:
            real = GetAncestor(hwnd, 2)  # GA_ROOT = 真正顶层
            return real or hwnd
    except Exception:
        pass
    try:
        frame_str = tk_root.frame()
        if frame_str:
            return int(frame_str, 16)
    except Exception:
        pass
    return 0


def _enable_dpi_awareness():
    """启用进程级 DPI 感知，使 winfo_screenwidth/height 返回真实像素"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ── 原生 Win32 网络检测 ──────────────────────────────
# 使用 wlanapi.dll + iphlpapi.dll 直接查询，无需 PowerShell 子进程。

WLAN_MAX_NAME_LENGTH = 256
_wlan_intf_opcode_current_connection = 7


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", _GUID),
        ("strInterfaceDescription", ctypes.c_wchar * WLAN_MAX_NAME_LENGTH),
        ("isState", ctypes.c_int),
    ]


class _WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
        ("InterfaceInfo", _WLAN_INTERFACE_INFO * 1),
    ]


class _DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", ctypes.c_ulong),
        ("ucSSID", ctypes.c_ubyte * 32),
    ]


class _DOT11_MAC_ADDRESS(ctypes.Structure):
    _fields_ = [("ucOctet", ctypes.c_ubyte * 6)]


class _WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", _DOT11_SSID),
        ("dot11BssType", ctypes.c_int),
        ("dot11Bssid", _DOT11_MAC_ADDRESS),
        ("dot11PhyType", ctypes.c_int),
        ("uDot11PhyIndex", ctypes.c_ulong),
        ("wlanSignalQuality", ctypes.c_ulong),
        ("ulRxRate", ctypes.c_ulong),
        ("ulTxRate", ctypes.c_ulong),
    ]


class _WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", ctypes.c_int),
        ("bOneXEnabled", ctypes.c_int),
        ("dot11AuthAlgorithm", ctypes.c_int),
        ("dot11CipherAlgorithm", ctypes.c_int),
    ]


class _WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", ctypes.c_int),
        ("wlanConnectionMode", ctypes.c_int),
        ("strProfileName", ctypes.c_wchar * WLAN_MAX_NAME_LENGTH),
        ("wlanAssociationAttributes", _WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", _WLAN_SECURITY_ATTRIBUTES),
    ]


class _IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


_IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", ctypes.c_ulong),
    ("IfIndex", ctypes.c_ulong),
    ("Next", ctypes.POINTER(_IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.c_void_p),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", ctypes.c_ulong),
    ("Flags", ctypes.c_ulong),
    ("Mtu", ctypes.c_ulong),
    ("IfType", ctypes.c_ulong),
    ("OperStatus", ctypes.c_int),
]


_wlanapi = ctypes.windll.wlanapi
_iphlpapi = ctypes.windll.iphlpapi

_WlanOpenHandle = _wlanapi.WlanOpenHandle
_WlanEnumInterfaces = _wlanapi.WlanEnumInterfaces
_WlanQueryInterface = _wlanapi.WlanQueryInterface
_WlanFreeMemory = _wlanapi.WlanFreeMemory
_WlanCloseHandle = _wlanapi.WlanCloseHandle
_GetAdaptersAddresses = _iphlpapi.GetAdaptersAddresses


def _query_wifi():
    """通过 WLAN API 查询当前 WiFi 连接，返回 (ssid, signal) 或 (None, 0)"""
    handle = ctypes.c_void_p()
    negotiated = ctypes.c_ulong()
    if _WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle)) != 0:
        return None, 0
    try:
        iflist = ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)()
        if _WlanEnumInterfaces(handle, None, ctypes.byref(iflist)) != 0 or not iflist:
            return None, 0
        try:
            if iflist.contents.dwNumberOfItems == 0:
                return None, 0
            # 多无线网卡时优先查询“已连接”(isState==1) 的那个接口，
            # 而不是固定取第一个
            interfaces = iflist.contents.InterfaceInfo
            idx = 0
            for i in range(iflist.contents.dwNumberOfItems):
                if interfaces[i].isState == 1:  # wlan_interface_state_connected
                    idx = i
                    break
            guid = interfaces[idx].InterfaceGuid
            data = ctypes.c_void_p()
            data_size = ctypes.c_ulong()
            ret = _WlanQueryInterface(
                handle, ctypes.byref(guid), _wlan_intf_opcode_current_connection,
                None, ctypes.byref(data_size), ctypes.byref(data), None)
            if ret != 0 or not data:
                return None, 0
            try:
                conn = ctypes.cast(data, ctypes.POINTER(_WLAN_CONNECTION_ATTRIBUTES)).contents
                assoc = conn.wlanAssociationAttributes
                ssid_len = int(assoc.dot11Ssid.uSSIDLength)
                if ssid_len <= 0:
                    return None, 0
                ssid_bytes = bytes(assoc.dot11Ssid.ucSSID[:ssid_len])
                ssid = ssid_bytes.decode("utf-8", errors="replace")
                return ssid, int(assoc.wlanSignalQuality)
            finally:
                _WlanFreeMemory(data)
        finally:
            _WlanFreeMemory(ctypes.cast(iflist, ctypes.c_void_p))
    finally:
        _WlanCloseHandle(handle, None)


def _query_other_adapter():
    """通过 GetAdaptersAddresses 查询状态为 Up 的有线/其他适配器名称。
    优先返回真实以太网卡(IfType 6)，避免 VPN/TAP/蓝牙等虚拟适配器抢在前面。"""
    size = ctypes.c_ulong(0)
    _GetAdaptersAddresses(0, 0, None, None, ctypes.byref(size))
    if size.value == 0:
        return None
    buf = ctypes.create_string_buffer(size.value)
    ptr = ctypes.cast(buf, ctypes.POINTER(_IP_ADAPTER_ADDRESSES))
    if _GetAdaptersAddresses(0, 0, None, ptr, ctypes.byref(size)) != 0:
        return None
    iftype_ethernet = 6   # IF_TYPE_ETHERNET_CSMACD
    iftype_loopback = 24  # IF_TYPE_SOFTWARE_LOOPBACK
    fallback = None
    cur = ptr
    while cur:
        addr = cur.contents
        if addr.OperStatus == 1 and addr.IfType != iftype_loopback:
            name = addr.FriendlyName
            if name:
                if addr.IfType == iftype_ethernet:
                    return name
                if fallback is None:
                    fallback = name
        cur = addr.Next
    return fallback


def _query_network():
    """查询网络状态，返回 dict: {Type, Name, Signal}"""
    ssid, signal = _query_wifi()
    if ssid:
        return {"Type": "wifi", "Name": ssid, "Signal": signal}
    name = _query_other_adapter()
    if name:
        return {"Type": "other", "Name": name, "Signal": 0}
    return {"Type": "none", "Name": "", "Signal": 0}


# ── 后台采样线程 ──────────────────────────────────────
_NET_CACHE = ("检测中...", False, None, 0)  # (display_text, is_wifi, ssid, signal)
_NET_LOCK = threading.Lock()
_NET_STOP = threading.Event()
_NET_THREAD = None
_NET_INTERVAL = 1
_NET_INTERVAL_LOCK = threading.Lock()


def _sampler_loop():
    """后台线程：周期查询网络状态并更新缓存"""
    global _NET_CACHE
    while not _NET_STOP.is_set():
        try:
            data = _query_network()
            display_text, is_wifi, ssid, signal = _parse_network_data(data)
        except Exception:
            display_text, is_wifi, ssid, signal = ("无网络连接", False, None, 0)
        with _NET_LOCK:
            _NET_CACHE = (display_text, is_wifi, ssid, signal)
        _NET_STOP.wait(_get_sampling_interval())


def _ensure_sampler():
    """确保采样线程已启动"""
    global _NET_THREAD
    if _NET_THREAD is not None and _NET_THREAD.is_alive():
        return
    _NET_STOP.clear()
    _NET_THREAD = threading.Thread(target=_sampler_loop, daemon=True)
    _NET_THREAD.start()


def _set_sampling_interval(sec):
    """更新后台采样线程的间隔（秒）"""
    global _NET_INTERVAL
    with _NET_INTERVAL_LOCK:
        _NET_INTERVAL = sec


def _get_sampling_interval():
    with _NET_INTERVAL_LOCK:
        return _NET_INTERVAL


def _parse_network_data(data):
    """将查询结果解析为 (display_text, is_wifi, ssid, signal)。"""
    net_type = data.get("Type", "none")
    name = data.get("Name", "")
    signal = data.get("Signal", 0)

    if net_type == "wifi" and name:
        return name, True, name, signal

    if net_type == "other" and name:
        return name, False, name, 0

    return "无网络连接", False, None, 0


def get_network_status():
    """获取缓存的网络状态 (text, is_wifi, ssid, signal)。若采样线程未启动则启动。"""
    _ensure_sampler()
    with _NET_LOCK:
        return _NET_CACHE


def _stop_network_worker():
    """停止后台采样线程"""
    _NET_STOP.set()


atexit.register(_stop_network_worker)


# ── 配置管理 ──────────────────────────────────────────
def load_config():
    defaults = {
        "x": None,
        "y": None,
        "locked": False,
        "opacity": 0.75,
        "font_size": 9,
        "refresh_interval": 1,
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

    # ── 归一化 / 容错：防止损坏、缺省或超范围配置导致异常行为 ──
    # refresh_interval ∈ {1, 2, 3, 5, 10}
    try:
        defaults["refresh_interval"] = int(defaults["refresh_interval"])
    except (TypeError, ValueError):
        defaults["refresh_interval"] = 1
    if defaults["refresh_interval"] not in (1, 2, 3, 5, 10):
        defaults["refresh_interval"] = 1

    # font_size ∈ [9, 16]
    try:
        defaults["font_size"] = int(defaults["font_size"])
    except (TypeError, ValueError):
        defaults["font_size"] = 9
    defaults["font_size"] = max(9, min(16, defaults["font_size"]))

    # opacity ∈ [0.2, 1.0]
    try:
        defaults["opacity"] = float(defaults["opacity"])
    except (TypeError, ValueError):
        defaults["opacity"] = 0.75
    defaults["opacity"] = max(0.2, min(1.0, defaults["opacity"]))

    defaults["locked"] = bool(defaults.get("locked"))
    defaults["auto_start"] = bool(defaults.get("auto_start"))
    if not isinstance(defaults.get("wifi_categories"), dict):
        defaults["wifi_categories"] = {}

    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 颜色主题 ──────────────────────────────────────────
COLOR_BG = "#1a1a2e"           # 悬浮窗外层背景
COLOR_INNER_BG = "#16213e"     # 内框背景
COLOR_BORDER = "#0f3460"       # 内框边框
COLOR_BORDER_DRAG = "#73c2fb"  # 拖动时边框高亮
COLOR_TEXT = "#e0e0e0"         # 主文字
COLOR_TEXT_DIM = "#a0a0a0"     # 次要文字 / 按钮
COLOR_DISABLED = "#555555"     # 禁用状态
COLOR_GREEN = "#00e676"        # 绿色类 WiFi
COLOR_RED = "#ff5252"          # 红色类 WiFi / 错误图标
COLOR_LOCKED = "#e94560"       # 已锁定指示 / 悬停警示
COLOR_NONE_TEXT = "#888888"    # 无网络文字（错误信号由红色图标承担）
MAX_TEXT_WIDTH = 220           # 悬浮窗文本最大像素宽度（超出截断）

# emoji 一律使用 Segoe UI Emoji，避免 Segoe UI Symbol 渲染为单色/缺字形
EMOJI_FONT = "Segoe UI Emoji"


def lock_icon(locked):
    return "🔒" if locked else "🔓"


# ── 信号小图标绘制 ────────────────────────────────────
_ICON_DARK = "#3d3d5c"


def _signal_level(signal):
    """信号强度 0-100 → 点亮格数 0-4"""
    if signal >= 80:
        return 4
    if signal >= 60:
        return 3
    if signal >= 40:
        return 2
    if signal >= 20:
        return 1
    return 0


def draw_signal_icon(canvas, icon_type, signal, color):
    """在 Canvas 上绘制小图标。icon_type: "wifi" | "other" | "none"
    图标元素以 20px 高度为基准随 canvas 尺寸等比缩放。"""
    canvas.delete("all")
    w = int(canvas["width"])
    h = int(canvas["height"])
    scale = min(w, h) / 20.0

    if icon_type == "wifi":
        cx, cy = w / 2, h - 2.5 * scale            # 扇形圆心在底部中点
        radii = [r * scale for r in (2.8, 4.9, 7.0, 9.1)]  # 4 段弧半径递增
        lit = _signal_level(signal)
        for i, r in enumerate(radii):
            if r > min(w, h) / 2 + 1:
                break
            arc_color = color if i < lit else _ICON_DARK
            canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=45, extent=90, style=tk.ARC,
                outline=arc_color, width=2.0,
            )
        dot = 1.5 * scale
        canvas.create_oval(
            cx - dot, cy - dot, cx + dot, cy + dot,
            fill=color, outline=color,
        )
    elif icon_type == "other":
        # 简化的以太网口:左侧插头线 + 右侧小矩形网口
        bx1, by1, bx2, by2 = w / 2 + 1, h / 2 - 3, w - 3, h / 2 + 3
        canvas.create_rectangle(
            bx1, by1, bx2, by2,
            fill=color, outline="", width=0,
        )
        canvas.create_line(bx1, by1, bx1, by2, fill=color)
        for i in range(3):
            ly = h / 2 - 2 + i * 2
            canvas.create_line(2, ly, bx1 - 1, ly, fill=color)
    else:
        # 无网络:红色 ✕
        canvas.create_line(3, 3, w - 3, h - 3, fill="#ff5252", width=2)
        canvas.create_line(w - 3, 3, 3, h - 3, fill="#ff5252", width=2)


# ── 开机自启管理 ──────────────────────────────────────
AUTO_START_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_auto_start_cmd():
    """生成开机自启的命令行（exe 版本直接指向自身，脚本版本指向 pythonw + 脚本）"""
    exe_path = os.path.abspath(sys.argv[0])
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，直接指向 exe 自身
        return f'"{exe_path}"'
    return f'"{sys.executable}" "{exe_path}"'


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
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return val == _get_auto_start_cmd()
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


# ── 悬停提示气泡 ──────────────────────────────────────
class _Tooltip:
    """轻量悬停提示：悬停 500ms 后在悬浮窗下方弹出，移开/点击后消失"""

    def __init__(self, root, get_text):
        self._root = root
        self._get_text = get_text
        self._win = None
        self._job = None

    def schedule(self, _event=None):
        self.cancel()
        self._job = self._root.after(500, self.show)

    def cancel(self, _event=None):
        if self._job is not None:
            try:
                self._root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.hide()

    def show(self):
        self._job = None
        if self._win is not None:
            return
        text = self._get_text()
        if not text:
            return
        try:
            win = tk.Toplevel(self._root)
            self._win = win
            win.overrideredirect(True)
            win.wm_attributes("-topmost", 1)
            win.configure(bg=COLOR_BORDER)
            tk.Label(
                win, text=text, justify=tk.LEFT,
                font=("Microsoft YaHei UI", 9),
                fg=COLOR_TEXT, bg=COLOR_INNER_BG,
                padx=8, pady=4,
            ).pack()
            x = self._root.winfo_x()
            y = self._root.winfo_y() + self._root.winfo_height() + 6
            win.geometry(f"+{x}+{y}")
        except Exception:
            self._win = None

    def hide(self):
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


# ── 系统托盘（纯 ctypes，零第三方依赖）──────────────────
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
WM_TRAYICON = 0x0401  # WM_USER + 1，托盘回调消息
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B  # NOTIFYICON_VERSION_4 下右键改用此消息
NIN_SELECT = 0x0400     # 部分版本左键点击以 NIN_SELECT 上报
NIN_KEYSELECT = 0x0401


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_ulong),
        ("dwStateMask", ctypes.c_ulong),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_ulong),
        ("guidItem", _GUID),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_int),
        ("xHotspot", ctypes.c_ulong),
        ("yHotspot", ctypes.c_ulong),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


_WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, ctypes.wintypes.HWND, ctypes.c_uint,
    ctypes.c_size_t, ctypes.c_ssize_t)


def _make_dot_icon(rgb):
    """生成指定 RGB 颜色的圆形托盘图标（圆外透明），返回 HICON；失败返回 None"""
    gdi32 = _gdi32
    u32 = user32
    try:
        size = u32.GetSystemMetrics(49) or 16  # SM_CXSMICON
        screen_dc = u32.GetDC(None)

        # 彩色位图：黑底 + 彩色圆
        color_dc = gdi32.CreateCompatibleDC(screen_dc)
        color_bm = gdi32.CreateCompatibleBitmap(screen_dc, size, size)
        old_color = gdi32.SelectObject(color_dc, color_bm)
        black = gdi32.CreateSolidBrush(0x00000000)
        color_brush = gdi32.CreateSolidBrush(rgb)
        gdi32.SelectObject(color_dc, black)
        gdi32.Rectangle(color_dc, 0, 0, size, size)
        gdi32.SelectObject(color_dc, color_brush)
        gdi32.Ellipse(color_dc, 1, 1, size - 1, size - 1)

        # 掩码位图（单色）：1=透明，0=不透明 → 白底 + 黑圆
        mask_dc = gdi32.CreateCompatibleDC(screen_dc)
        mask_bm = gdi32.CreateBitmap(size, size, 1, 1, None)
        old_mask = gdi32.SelectObject(mask_dc, mask_bm)
        white = gdi32.CreateSolidBrush(0x00FFFFFF)
        gdi32.SelectObject(mask_dc, white)
        gdi32.Rectangle(mask_dc, 0, 0, size, size)
        gdi32.SelectObject(mask_dc, black)
        gdi32.Ellipse(mask_dc, 1, 1, size - 1, size - 1)

        info = _ICONINFO(1, 0, 0, mask_bm, color_bm)
        hicon = u32.CreateIconIndirect(ctypes.byref(info))

        # 清理 GDI 资源（ICON 创建后位图即可释放）
        gdi32.SelectObject(color_dc, old_color)
        gdi32.SelectObject(mask_dc, old_mask)
        for obj in (black, color_brush, white, color_bm, mask_bm):
            if obj:
                gdi32.DeleteObject(obj)
        gdi32.DeleteDC(color_dc)
        gdi32.DeleteDC(mask_dc)
        u32.ReleaseDC(None, screen_dc)
        return hicon or None
    except Exception:
        return None


# ── 主窗口类 ──────────────────────────────────────────
class NetworkOverlay:
    def __init__(self):
        self.config = load_config()
        # 启动时把配置里的刷新间隔同步给后台采样线程（否则菜单中改过后
        # 重启又回到默认 1 秒，后台仍然高频轮询）
        _set_sampling_interval(self.config["refresh_interval"])
        # 启动时同步实际注册表状态到配置（防止手动删除注册表后配置残留）
        actual = is_auto_start_enabled()
        if self.config.get("auto_start") != actual:
            self.config["auto_start"] = actual
            save_config(self.config)
        self._exiting = False
        self._mgmt_window = None  # WiFi 管理窗口引用
        self._refresh_job = None  # 当前刷新定时器 id（防止定时器叠加）
        self._first_run = self.config.get("x") is None  # 首次运行（无位置记录）
        self._last_status = ("检测中...", False, None, 0)  # 最近一次网络状态
        self._click_through = False  # 锁定时选择性穿透标志
        self._wndproc_cb = None      # 子类化窗口过程回调引用（防 GC）
        self._old_wndproc = None     # 原窗口过程
        self._tray_events = []       # 托盘回调暂存队列（wndproc 内禁止调 Tk，见 _tray_wndproc）

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.geometry("1x28")

        # 使用纯色背景（不再用 transparentcolor，避免与扩展样式冲突）
        self.bg_color = COLOR_BG
        self.inner_bg = COLOR_INNER_BG
        self.root.configure(bg=self.bg_color)
        self.root.wm_attributes("-topmost", 1)
        self.root.wm_attributes("-alpha", self.config["opacity"])

        self._text_font = tkfont.Font(
            family="Microsoft YaHei UI",
            size=self.config["font_size"], weight="bold")
        self._drag_data = {"x": 0, "y": 0, "dragging": False}
        self.network_text = ""

        self._build_ui()
        self._set_initial_position()
        self._build_context_menu()
        self._bind_events()
        self._apply_window_ex_styles()
        # 先子类化窗口过程（托盘回调 + 锁定穿透的命中测试共用），
        # 再注册托盘；即使托盘初始化失败，锁定穿透仍可用。
        self._install_wndproc()
        self._setup_tray()

        self._refresh_network()
        self.root.deiconify()

        self._sync_lock_visuals()
        if self.config["locked"]:
            self._set_click_through(True)

        if self._first_run:
            self.root.after(300, self._show_first_run_hint)

    # ── UI 构建 ──────────────────────────────────
    def _icon_dims(self):
        """信号图标尺寸随字号缩放（9px 字号时约 22x20）"""
        size = self.config["font_size"]
        return size * 2 + 4, size * 2 + 2

    def _truncate_text(self, text):
        """按像素宽度截断过长文本，超出部分以 … 收尾，避免窗口宽度失控"""
        try:
            if self._text_font.measure(text) <= MAX_TEXT_WIDTH:
                return text
            while text and self._text_font.measure(text + "…") > MAX_TEXT_WIDTH:
                text = text[:-1]
            return text + "…" if text else text
        except Exception:
            return text

    def _build_ui(self):
        self.main_frame = tk.Frame(self.root, bg=self.bg_color, highlightthickness=0, bd=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.inner_frame = tk.Frame(
            self.main_frame, bg=self.inner_bg,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_BORDER, bd=0,
        )
        self.inner_frame.pack(fill=tk.BOTH, expand=True)

        icon_w, icon_h = self._icon_dims()
        self.signal_canvas = tk.Canvas(
            self.inner_frame, width=icon_w, height=icon_h,
            bg=self.inner_bg, highlightthickness=0, bd=0,
        )
        self.signal_canvas.pack(side=tk.LEFT, padx=(5, 1), pady=1)

        self.net_label = tk.Label(
            self.inner_frame, text="检测中...",
            fg=COLOR_TEXT, bg=self.inner_bg,
            font=self._text_font,
            anchor="w", padx=4, pady=1,
        )
        self.net_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lock_btn_text = tk.StringVar(value=lock_icon(self.config["locked"]))
        self.lock_btn = tk.Label(
            self.inner_frame, textvariable=self.lock_btn_text,
            fg=COLOR_TEXT_DIM, bg=self.inner_bg,
            font=(EMOJI_FONT, 9), padx=4, pady=1, cursor="hand2",
        )
        self.lock_btn.pack(side=tk.RIGHT)

        self.close_btn = tk.Label(
            self.inner_frame, text="✕",
            fg=COLOR_TEXT_DIM, bg=self.inner_bg,
            font=("Segoe UI Symbol", 9), padx=3, pady=1, cursor="hand2",
        )
        self.close_btn.pack(side=tk.RIGHT, padx=(6, 2))

    def _build_context_menu(self):
        menu_font = ("Microsoft YaHei UI", 9)
        # 菜单变量：radiobutton/checkbutton 直接显示当前值，且与 config 双向同步
        self.opacity_var = tk.DoubleVar(value=self.config["opacity"])
        self.font_size_var = tk.IntVar(value=self.config["font_size"])
        self.refresh_var = tk.IntVar(value=self.config.get("refresh_interval", 1))
        self.auto_start_var = tk.BooleanVar(value=bool(self.config.get("auto_start")))

        self.context_menu = tk.Menu(self.root, tearoff=0, font=menu_font)
        self.context_menu.add_command(label="🔓 切换锁定 / 解锁", command=self._toggle_lock)
        self.context_menu.add_separator()

        opacity_menu = tk.Menu(self.context_menu, tearoff=0, font=menu_font)
        for val, label in [(0.5, "50%"), (0.65, "65%"), (0.75, "75% (默认)"),
                           (0.85, "85%"), (0.95, "95%")]:
            opacity_menu.add_radiobutton(
                label=label, variable=self.opacity_var, value=val,
                command=lambda v=val: self._set_opacity(v))
        self.context_menu.add_cascade(label="🔅 透明度", menu=opacity_menu)

        font_menu = tk.Menu(self.context_menu, tearoff=0, font=menu_font)
        for size in [9, 10, 11, 12, 14, 16]:
            font_menu.add_radiobutton(
                label=f"{size}px", variable=self.font_size_var, value=size,
                command=lambda s=size: self._set_font_size(s))
        self.context_menu.add_cascade(label="🔤 字号", menu=font_menu)

        refresh_menu = tk.Menu(self.context_menu, tearoff=0, font=menu_font)
        for sec in [1, 2, 3, 5, 10]:
            refresh_menu.add_radiobutton(
                label=f"{sec} 秒", variable=self.refresh_var, value=sec,
                command=lambda s=sec: self._set_refresh_interval(s))
        self.context_menu.add_cascade(label="⏱ 刷新间隔", menu=refresh_menu)

        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 手动刷新", command=self._refresh_network)
        self.context_menu.add_command(label="📋 管理 WiFi 分类", command=self._open_wifi_manager)
        self.context_menu.add_checkbutton(
            label="☑ 开机自动启动", variable=self.auto_start_var,
            command=self._toggle_auto_start)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📍 重置位置到右上角", command=self._reset_position)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 退出", command=self._quit)

        # ✕ 按钮的退出确认菜单（防止误触直接退出）
        self.confirm_menu = tk.Menu(self.root, tearoff=0, font=menu_font)
        self.confirm_menu.add_command(label="✔ 确认退出", command=self._quit)
        self.confirm_menu.add_command(label="✕ 取消", command=lambda: None)

        # 托盘右键专用菜单：“退出”放到最顶部 —— 悬浮窗一旦异常/穿透锁定，
        # 锁图标虽可点击解锁，但托盘仍是最可靠的退出入口，必须保证能一键关闭。
        self.tray_menu = tk.Menu(self.root, tearoff=0, font=menu_font)
        self.tray_menu.add_command(label="❌ 退出 NetworkOverlay", command=self._quit)
        self.tray_menu.add_separator()
        self.tray_menu.add_command(label="🔓 切换锁定 / 解锁", command=self._toggle_lock)
        self.tray_menu.add_command(label="📍 重置位置到右上角", command=self._reset_position)
        self.tray_menu.add_separator()
        self.tray_menu.add_command(label="☰ 完整设置菜单…", command=self._popup_full_menu)

        # 全部菜单集合（含级联子菜单），用于“左键不落在菜单上就关闭”的命中判断
        self._all_menus = [self.context_menu, self.tray_menu, self.confirm_menu,
                           opacity_menu, font_menu, refresh_menu]

    # ── 事件绑定 ──────────────────────────────────
    def _bind_events(self):
        self._tooltip = _Tooltip(self.root, self._tooltip_text)

        for widget in [self.inner_frame, self.net_label, self.signal_canvas]:
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)
            widget.bind("<Enter>", self._tooltip.schedule)
            widget.bind("<Leave>", self._tooltip.cancel)
            widget.bind("<Button-1>", self._tooltip.cancel, add="+")

        for widget in [self.inner_frame, self.net_label, self.signal_canvas, self.lock_btn]:
            widget.bind("<Button-3>", self._show_context_menu)

        # 点击锁图标切换锁定/解锁。锁定穿透时窗口整体对命中测试透明，
        # 但锁图标区域仍可命中（见 _selective_hit_test），所以锁定后
        # 也能再次点击 🔒 直接解锁，无需借助托盘/右键菜单。
        self.lock_btn.bind("<Button-1>", lambda e: self._toggle_lock())
        self.close_btn.bind("<Button-1>", self._confirm_quit)

        # 按钮悬停反馈（锁定后 ✕ 为禁用态，不响应 hover；🔒 悬停提示可点击解锁）
        self.lock_btn.bind("<Enter>", lambda e: self.lock_btn.configure(
            fg=COLOR_LOCKED if self.config["locked"] else COLOR_TEXT))
        self.lock_btn.bind("<Leave>", lambda e: self._sync_lock_visuals())
        self.close_btn.bind("<Enter>", lambda e: None if self.config["locked"]
                            else self.close_btn.configure(fg=COLOR_RED))
        self.close_btn.bind("<Leave>", lambda e: self._sync_lock_visuals())

        self.inner_frame.bind("<MouseWheel>", self._on_scroll)
        self.net_label.bind("<MouseWheel>", self._on_scroll)
        self.signal_canvas.bind("<MouseWheel>", self._on_scroll)
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

    # ── 系统托盘 ─────────────────────────────────
    def _setup_tray(self):
        """注册系统托盘图标：左键切换锁定，右键弹出完整菜单。
        锁定穿透后窗口不接收多数鼠标事件，托盘是最可靠的操作/关闭入口。
        窗口过程已在 _install_wndproc 中统一子类化（托盘回调 + 命中测试）。"""
        self._tray_nid = None
        self._tray_state = None
        self._tray_icons = {}
        try:
            hwnd = get_hwnd(self.root)
            if not hwnd:
                return
            self._tray_icons = {
                "green": _make_dot_icon(0x0076E600),  # #00e676
                "red": _make_dot_icon(0x005252FF),    # #ff5252
                "gray": _make_dot_icon(0x00A0A0A0),   # #a0a0a0
            }
            if not self._tray_icons["gray"]:
                return
            # 兜底：正常流程在 __init__ 已装好窗口过程，这里仅防异常路径漏装。
            if self._old_wndproc is None:
                self._install_wndproc()
            if not self._old_wndproc:
                return

            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self._tray_icons["gray"]
            nid.szTip = "网络状态悬浮窗"
            # 托盘注册失败时不要还原窗口过程——它同时承担锁定穿透的命中测试。
            if not ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self._tray_nid = None
                return
            # 默认版本（0）：右键以 WM_RBUTTONUP、左键以 WM_LBUTTONUP 经回调上报，
            # 现行 _tray_wndproc 已稳定处理。NOTIFYICON_VERSION_4 下右键回调形式不稳
            # （lParam 或独立 WM_CONTEXTMENU 不定），会导致右键菜单打不开。
            nid.uVersion = 0
            ctypes.windll.shell32.Shell_NotifyIconW(
                NIM_SETVERSION, ctypes.byref(nid))  # 还原为默认回调行为
            self._tray_nid = nid
            self._drain_tray_events()  # 启动托盘事件轮询（wndproc 只入队，这里在 Tk 循环中执行）
        except Exception:
            self._tray_nid = None

    def _install_wndproc(self):
        """子类化根窗口过程，用于：
        1) 接收系统托盘回调消息；
        2) 锁定时选择性命中测试（WM_NCHITTEST —— 锁图标区域仍可点击解锁）。
        与托盘创建完全解耦：即使托盘初始化失败，锁定穿透/点击解锁依旧可用。"""
        if self._old_wndproc is not None:
            return
        try:
            hwnd = get_hwnd(self.root)
            if not hwnd:
                return
            # 实例属性保持回调引用防止被 GC
            self._wndproc_cb = _WNDPROCTYPE(self._tray_wndproc)
            self._old_wndproc = SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC,
                ctypes.cast(self._wndproc_cb, ctypes.c_void_p).value)
            if not self._old_wndproc:
                self._old_wndproc = None
        except Exception:
            self._old_wndproc = None

    def _tray_wndproc(self, hwnd, msg, wparam, lparam):
        """窗口过程：拦截托盘回调与锁定时的选择性命中测试，其余透传原过程

        不同 NOTIFYICON 版本下，点击消息的 lParam 不同：
        - 默认/旧版：WM_LBUTTONUP / WM_RBUTTONUP；
        - NOTIFYICON_VERSION_4：左键仍发 WM_LBUTTONUP，右键改为发 WM_CONTEXTMENU；
        - 部分环境下以 NIN_SELECT / NIN_KEYSELECT 上报左键。

        【重要】此回调运行在 Windows 消息派发上下文中，绝不能直接调用任何
        Tk API（含 root.after）——实测会触发 Fatal Python error:
        PyEval_RestoreThread（GIL 线程状态错乱）导致进程闪退（见 _tray_min* 探针）。
        因此这里只把事件写入纯 Python 队列，由 _drain_tray_events 在正常
        Tk 事件循环中轮询处理。WM_NCHITTEST 分支的同步 winfo 读取已验证安全。"""
        if msg == WM_TRAYICON:
            if lparam in (WM_LBUTTONUP, NIN_SELECT, NIN_KEYSELECT):
                self._tray_events.append("left")
            elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._tray_events.append("right")
            return 0
        if (msg == WM_NCHITTEST and self._click_through
                and not self._exiting):
            return self._selective_hit_test(lparam)
        return CallWindowProcW(self._old_wndproc, hwnd, msg, wparam, lparam)

    def _drain_tray_events(self):
        """在 Tk 事件循环中轮询处理托盘回调队列（wndproc 只入队，这里出队执行）。
        调用点均为标准 Tk 回调上下文，tk_popup 等操作安全。"""
        events, self._tray_events = self._tray_events, []
        for ev in events:
            if self._exiting:
                break
            if ev == "left":
                self._on_tray_left()
            elif ev == "right":
                self._on_tray_right()
        if not self._exiting:
            self.root.after(50, self._drain_tray_events)

    def _selective_hit_test(self, lparam):
        """锁定穿透时选择性命中：仅锁图标区域可点击（返回 HTCLIENT，点击解锁），
        其余区域返回 HTTRANSPARENT 穿透给下层窗口。

        lParam 高/低 16 位为带符号屏幕坐标（x | y<<16）。进程已启用 DPI
        感知（_enable_dpi_awareness），WM_NCHITTEST 与 winfo_rootx/y 都基于
        真实像素，坐标系一致。"""
        try:
            x = lparam & 0xFFFF
            y = (lparam >> 16) & 0xFFFF
            if x & 0x8000:
                x -= 0x10000
            if y & 0x8000:
                y -= 0x10000
            bx = self.lock_btn.winfo_rootx()
            by = self.lock_btn.winfo_rooty()
            bw = self.lock_btn.winfo_width()
            bh = self.lock_btn.winfo_height()
            if bw > 0 and bh > 0 and bx <= x < bx + bw and by <= y < by + bh:
                return HTCLIENT
        except Exception:
            pass
        return HTTRANSPARENT

    def _on_tray_left(self):
        if not self._exiting:
            self._toggle_lock()

    def _on_tray_right(self):
        """托盘右键：弹出托盘专用菜单（顶部为『退出』，是最可靠的关闭入口）"""
        self._popup_menu(self.tray_menu)

    def _popup_full_menu(self):
        """托盘菜单中的『完整设置菜单』入口：在鼠标位置弹出完整右键菜单"""
        self._popup_menu(self.context_menu)

    def _popup_menu(self, menu):
        """在鼠标位置弹出指定菜单（前置前台并补发 WM_NULL，保证菜单正常收起）。
        弹出后启动 _monitor_menu_close：只要左键不落在菜单上（桌面/其他程序/
        悬浮窗），就关闭菜单——本窗口为 noactivate 工具窗，Tk 依赖焦点丢失的
        自动关闭机制在此失效，需主动轮询检测。"""
        try:
            hwnd = get_hwnd(self.root)
            pt = _POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # 菜单弹出前置前台，否则点击他处时菜单不收起
            user32.SetForegroundWindow(hwnd)
            menu.tk_popup(pt.x, pt.y)
            user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL，帮助菜单正常关闭
            self._monitor_menu_close(menu)
        except Exception:
            pass

    def _monitor_menu_close(self, menu, prev_down=False):
        """轮询监控菜单：检测左键“按下沿”，若按下位置不落在任何可见菜单
        （含级联子菜单）上，则关闭该菜单并结束监控。菜单被选中自动收起或
        程序退出时同样结束。"""
        if self._exiting:
            return
        try:
            if not menu.winfo_ismapped():
                return  # 菜单已被选中/收起
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)  # VK_LBUTTON
            if down and not prev_down:  # 左键按下沿
                pt = _POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                if not self._point_on_menu(pt.x, pt.y):
                    menu.unpost()
                    return
            self.root.after(40, lambda: self._monitor_menu_close(menu, down))
        except Exception:
            pass

    def _point_on_menu(self, x, y):
        """判断屏幕坐标 (x, y) 是否落在任一可见菜单窗口的矩形内"""
        for m in getattr(self, "_all_menus", ()):
            try:
                if not m.winfo_ismapped():
                    continue
                h = m.winfo_id()
                if not h:
                    continue
                rect = _RECT()
                if user32.GetWindowRect(h, ctypes.byref(rect)):
                    if rect.left <= x < rect.right and rect.top <= y < rect.bottom:
                        return True
            except Exception:
                continue
        return False

    def _update_tray(self, text="", is_wifi=False, ssid=None):
        """根据网络状态切换托盘圆点颜色并更新提示文本"""
        nid = getattr(self, "_tray_nid", None)
        if nid is None:
            return
        if is_wifi and ssid:
            cat = self.config.get("wifi_categories", {}).get(ssid)
            state = "green" if cat == "green" else "red"
        else:
            state = "gray"
        try:
            if state != self._tray_state:
                self._tray_state = state
                nid.hIcon = self._tray_icons[state]
                nid.uFlags = NIF_ICON
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass
        self._update_tray_tip(text)

    def _update_tray_tip(self, text=None):
        """更新托盘悬停提示：网络名 + 锁定状态"""
        nid = getattr(self, "_tray_nid", None)
        if nid is None:
            return
        try:
            if text is None:
                text = self._last_status[0]
            lock = "已锁定" if self.config["locked"] else "未锁定"
            nid.szTip = f"{text} · {lock}"[:120]
            nid.uFlags = NIF_TIP
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def _teardown_tray(self):
        """移除托盘图标、恢复窗口过程、销毁图标资源"""
        nid = getattr(self, "_tray_nid", None)
        if nid is not None:
            try:
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
            self._tray_nid = None
        try:
            hwnd = get_hwnd(self.root)
            if hwnd and self._old_wndproc:
                SetWindowLongPtrW(hwnd, GWLP_WNDPROC, self._old_wndproc)
                self._old_wndproc = None
        except Exception:
            pass
        for hicon in getattr(self, "_tray_icons", {}).values():
            if hicon:
                try:
                    user32.DestroyIcon(hicon)
                except Exception:
                    pass
        self._tray_icons = {}

    # ── 位置 ──────────────────────────────────────
    def _resize_to_content(self):
        """按内容自适应窗口尺寸（宽度随文本伸缩，高度固定），位置保持不变"""
        self.root.update_idletasks()
        try:
            w = max(120, self.main_frame.winfo_reqwidth())
            h = max(28, self.main_frame.winfo_reqheight())
            self.root.geometry(f"{w}x{h}")
        except Exception:
            pass

    def _set_initial_position(self):
        # 使用虚拟屏幕范围，支持副屏在主屏左侧/上方（坐标为负值）的场景
        try:
            vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        except Exception:
            vx, vy, vw, vh = 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.config.get("x")
        y = self.config.get("y")
        if x is not None and y is not None:
            # 允许负坐标，但仍在虚拟屏幕边界内
            x = max(vx, min(x, vx + vw - 240))
            y = max(vy, min(y, vy + vh - 40))
        else:
            # 默认放主屏右上角
            x = self.root.winfo_screenwidth() - 260
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
        self.root.geometry(f"+{screen_w - 260}+20")
        self._save_position()

    def _show_first_run_hint(self):
        """首次运行时显示操作提示气泡，6 秒后自动消失"""
        if self._exiting:
            return
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.wm_attributes("-topmost", 1)
            win.configure(bg=COLOR_BORDER)
            tk.Label(
                win,
                text="左键拖动移动 · 右键打开菜单 · 滚轮调透明度\n"
                     "点击 🔒 锁定后鼠标穿透，再次点击 🔒 即可解锁 / 弹出菜单",
                justify=tk.LEFT,
                font=("Microsoft YaHei UI", 9),
                fg=COLOR_TEXT, bg=COLOR_INNER_BG,
                padx=10, pady=6,
            ).pack()
            x = self.root.winfo_x()
            y = self.root.winfo_y() + self.root.winfo_height() + 6
            win.geometry(f"+{x}+{y}")
            win.after(6000, lambda: win.destroy())
        except Exception:
            pass

    # ── 拖动事件 ─────────────────────────────────
    def _on_drag_start(self, event):
        if self.config["locked"]:
            return
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._drag_data["dragging"] = True
        # 拖动期间边框高亮，提供明确的抓取反馈
        self.inner_frame.configure(
            highlightbackground=COLOR_BORDER_DRAG,
            highlightcolor=COLOR_BORDER_DRAG)

    def _on_drag_motion(self, event):
        if not self._drag_data["dragging"] or self.config["locked"]:
            return
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        new_x = self.root.winfo_x() + dx
        new_y = self.root.winfo_y() + dy
        self.root.geometry(f"+{new_x}+{new_y}")

    def _on_drag_end(self, event):
        if self._drag_data["dragging"]:
            self.inner_frame.configure(
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER)
        self._drag_data["dragging"] = False
        self._save_position()

    def _on_scroll(self, event):
        delta = 0.03 if event.delta > 0 else -0.03
        new_val = round(self.config["opacity"] + delta, 2)
        self._set_opacity(max(0.2, min(1.0, new_val)))

    def _show_context_menu(self, event):
        self._popup_menu(self.context_menu)

    def _confirm_quit(self, event):
        """点击 ✕ 时弹出确认菜单，避免误触直接退出"""
        if self.config["locked"]:
            return
        self._popup_menu(self.confirm_menu)

    def _sync_lock_visuals(self):
        """根据锁定状态同步 🔒/✕ 按钮的颜色与禁用态"""
        locked = self.config["locked"]
        self.lock_btn_text.set(lock_icon(locked))
        self.lock_btn.configure(fg=COLOR_LOCKED if locked else COLOR_TEXT_DIM)
        self.close_btn.configure(fg=COLOR_DISABLED if locked else COLOR_TEXT_DIM)

    def _tooltip_text(self):
        """生成悬停提示内容（连接类型 / 信号 / 锁定状态 / 刷新间隔）"""
        text, is_wifi, ssid, signal = self._last_status
        if is_wifi:
            detail = f"WiFi：{text} · 信号 {signal}%"
        elif ssid:
            detail = f"有线/其他：{text}"
        else:
            detail = text
        lock = "已锁定（其余穿透，点击 🔒 解锁）" if self.config["locked"] else "未锁定（点击 🔒 锁定）"
        interval = self.config.get("refresh_interval", 1)
        return f"{detail}\n{lock} · 每 {interval}s 刷新 · 滚轮调透明度"

    # ── 功能 ─────────────────────────────────────
    def _toggle_lock(self):
        self.config["locked"] = not self.config["locked"]
        self._sync_lock_visuals()
        self._set_click_through(self.config["locked"])
        save_config(self.config)
        self._update_tray_tip()

    def _set_click_through(self, enable):
        """锁定后实现『选择性』鼠标穿透：锁图标区域保持可点击，其余全部穿透。

        说明（旧实现的问题）：
        - 旧实现给整个窗口加 WS_EX_TRANSPARENT，窗口对命中测试完全透明，
          连锁图标也点不到——这正是『锁定后无法点击 🔒 解锁』的根源。
        - 新实现不再加该样式，改由已子类化的窗口过程处理 WM_NCHITTEST：
          锁图标区域返回 HTCLIENT（可点击解锁），其余返回 HTTRANSPARENT（穿透）。
          HTTRANSPARENT 与 WS_EX_TRANSPARENT 效果相同——本窗口被命中测试跳过、
          点击落在下层窗口；已在真实屏幕上实测对跨进程窗口同样生效。

        注意：此处不要附加/断言 WS_EX_LAYERED。tkinter 通过
        wm_attributes("-alpha") 已把窗口设为分层窗口（LWA_ALPHA），
        这里重设 WS_EX_LAYERED 会破坏分层重定向表面，导致窗口渲染成黑块。
        """
        self._click_through = bool(enable)
        try:
            hwnd = get_hwnd(self.root)
            if not hwnd:
                return
            # 确保不残留整窗穿透样式，否则本窗口的 WM_NCHITTEST 收不到
            # （WS_EX_TRANSPARENT 会在命中测试前直接跳过整窗）。
            ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if ex_style & WS_EX_TRANSPARENT:
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_style & ~WS_EX_TRANSPARENT)
                SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _set_opacity(self, val):
        self.config["opacity"] = val
        self.opacity_var.set(val)
        self.root.wm_attributes("-alpha", val)
        save_config(self.config)

    def _set_font_size(self, size):
        self.config["font_size"] = size
        self.font_size_var.set(size)
        self._text_font = tkfont.Font(
            family="Microsoft YaHei UI", size=size, weight="bold")
        self.net_label.configure(font=self._text_font)
        # 图标随字号缩放
        icon_w, icon_h = self._icon_dims()
        self.signal_canvas.configure(width=icon_w, height=icon_h)
        save_config(self.config)
        self.network_text = None  # 强制按新字体重排文本与截断
        self._refresh_network()

    def _set_refresh_interval(self, sec):
        self.config["refresh_interval"] = sec
        self.refresh_var.set(sec)
        save_config(self.config)
        _set_sampling_interval(sec)
        self._schedule_refresh()

    def _schedule_refresh(self):
        """取消旧的刷新定时器并注册新的，避免定时器叠加"""
        if self._refresh_job is not None:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None
        interval_ms = self.config.get("refresh_interval", 5) * 1000
        self._refresh_job = self.root.after(interval_ms, self._refresh_network)

    def _toggle_auto_start(self):
        """切换开机自启状态（由菜单 checkbutton 触发，变量值已更新）"""
        new_state = bool(self.auto_start_var.get())
        set_auto_start(new_state)
        self.config["auto_start"] = new_state
        save_config(self.config)

    def _refresh_network(self):
        """刷新网络状态显示"""
        if self._exiting:
            return
        try:
            text, is_wifi, ssid, signal = get_network_status()
            self._last_status = (text, is_wifi, ssid, signal)
            if text != self.network_text:
                self.network_text = text
                self.net_label.configure(text=self._truncate_text(text))

            # WiFi 分类颜色（始终检查，因分类可能在管理窗口中变更）
            icon_color = COLOR_TEXT_DIM
            icon_type = "none"
            if is_wifi and ssid:
                icon_type = "wifi"
                categories = self.config.setdefault("wifi_categories", {})
                if ssid not in categories:
                    # 首次连接 → 红色
                    categories[ssid] = "red"
                    save_config(self.config)
                if categories.get(ssid) == "green":
                    icon_color = COLOR_GREEN  # 绿色类
                else:
                    icon_color = COLOR_RED    # 红色类
                self.net_label.configure(fg=icon_color)
            elif ssid:
                icon_type = "other"
                self.net_label.configure(fg=COLOR_TEXT_DIM)  # 有线/其他连接 → 灰色
            else:
                # 无网络 → 文字灰色，错误信号由红色 ✕ 图标承担（与红色类 WiFi 区分语义）
                self.net_label.configure(fg=COLOR_NONE_TEXT)

            draw_signal_icon(self.signal_canvas, icon_type, signal, icon_color)
            self._resize_to_content()
            self._update_tray(text, is_wifi, ssid)
        except Exception:
            pass  # 静默处理刷新错误，不影响定时器继续
        self._schedule_refresh()

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
        _, _, cur_ssid, _ = get_network_status()
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
        canvas_win = canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        # 列表宽度随窗口拉伸，消除右侧留白
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            canvas_win, width=e.width))
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

        def _delete_ssid(ssid):
            """从分类记录中删除该 SSID 并重建列表"""
            if ssid in categories:
                del categories[ssid]
            save_config(self.config)
            self._refresh_network()
            _rebuild_list()

        def _rebuild_list():
            """清空并重建 SSID 列表（用于删除后刷新）"""
            for w in list_frame.winfo_children():
                w.destroy()
            ssid_vars.clear()
            _populate_list()

        def _populate_list():
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
                return
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

                # 删除按钮
                del_btn = tk.Label(
                    row,
                    text="🗑",
                    font=(EMOJI_FONT, 9),
                    fg="#888", bg="#16213e",
                    padx=4, cursor="hand2",
                )
                del_btn.pack(side=tk.RIGHT)
                del_btn.bind("<Button-1>", lambda e, s=ssid: _delete_ssid(s))
                del_btn.bind("<Enter>", lambda e, b=del_btn: b.configure(fg="#e94560"))
                del_btn.bind("<Leave>", lambda e, b=del_btn: b.configure(fg="#888"))

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

        _populate_list()

        # ── 底部按钮 ──
        btn_frame = tk.Frame(win, bg="#1a1a2e", pady=10)
        btn_frame.pack(fill=tk.X, padx=16)

        close_btn = tk.Label(
            btn_frame,
            text="关 闭",
            font=("Microsoft YaHei UI", 10, "bold"),
            fg="#e0e0e0", bg="#0f3460",
            padx=20, pady=4, cursor="hand2",
            highlightthickness=1, highlightbackground="#3d5a80",
        )
        close_btn.pack()
        close_btn.bind("<Button-1>", lambda e: _on_mgmt_close())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(bg="#1a5276"))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(bg="#0f3460"))

        # 按 Escape / Return 关闭
        win.bind("<Escape>", lambda e: _on_mgmt_close())
        win.bind("<Return>", lambda e: _on_mgmt_close())

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
        self._teardown_tray()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    # 单实例检测（使用锁文件，比 FindWindowW 更可靠）
    if not acquire_lock():
        try:
            user32.MessageBoxW(0,
                               "网络悬浮窗已在运行中。\n"
                               "请查看系统托盘区的悬浮窗图标（左键切换锁定，右键打开菜单）。\n"
                               "如果在任务管理器中结束 NetworkOverlay 进程后仍无法启动，\n"
                               "请删除程序目录下的 .overlay.lock 文件。",
                               APP_NAME, 0x40)
        except Exception:
            pass
        sys.exit(0)

    _enable_dpi_awareness()
    app = NetworkOverlay()
    app.run()
