# -*- coding: utf-8 -*-
"""
逐字自动输入 (Auto Input) · v1.0.0
作者：PakLua

在上方文本框里写好要录入的内容，把光标点进目标输入框，
按 F9（或点击「开始输入」）即可逐字模拟键盘输入；F8 重新开始，ESC 紧急停止。

主要特性：
  * 圆角卡片式界面，自定义按钮 / 开关 / 分段控件、实时进度与倒计时环
  * 速度预设 + 精细调节，实时字数 / 预计耗时统计
  * 设置自动记忆，文本可导入导出
  * 高 DPI 感知，界面在高分屏上不模糊

核心输入逻辑基于 Windows SendInput 逐字符发送，可绕过网页的粘贴限制；
只使用 Python 标准库，无需安装任何第三方包，且**不联网、不收集任何数据**。
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import random
import re
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk


# --------------------------------------------------------------------------- #
# 应用信息
# --------------------------------------------------------------------------- #
APP_NAME = "逐字自动输入"
APP_VERSION = "1.0.1"
APP_AUTHOR = "PakLua"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "PakLua" / "AutoInput"
CONFIG_PATH = CONFIG_DIR / "settings.json"


# --------------------------------------------------------------------------- #
# 高 DPI
# --------------------------------------------------------------------------- #
def enable_dpi_awareness() -> float:
    """开启高 DPI 感知，返回缩放系数（96 DPI = 1.0）。"""
    scale = 1.0
    try:  # Windows 8.1+：按显示器 DPI 感知
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi:
            scale = dpi / 96.0
    except Exception:
        pass
    return scale


# --------------------------------------------------------------------------- #
# Windows SendInput 封装
# --------------------------------------------------------------------------- #
user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_BACK = 0x08
VK_F8 = 0x77
VK_F9 = 0x78
VK_CONTROL = 0x11
VK_A = 0x41
VK_C = 0x43
VK_DELETE = 0x2E

EXIT_SENTINEL = "\x00EXIT_LIST\x00"


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]


def _kb_input(vk: int, scan: int, flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    return inp


def send_unicode(ch: str) -> None:
    """以 Unicode 方式发送一个字符（模拟真实敲键，支持中文）。"""
    code = ord(ch)
    if code > 0xFFFF:  # 需要 UTF-16 代理对
        code -= 0x10000
        hi = 0xD800 + (code >> 10)
        lo = 0xDC00 + (code & 0x3FF)
        seq = (
            _kb_input(0, hi, KEYEVENTF_UNICODE),
            _kb_input(0, lo, KEYEVENTF_UNICODE),
            _kb_input(0, lo, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            _kb_input(0, hi, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        )
    else:
        seq = (
            _kb_input(0, code, KEYEVENTF_UNICODE),
            _kb_input(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        )
    arr = INPUT * len(seq)
    user32.SendInput(len(seq), ctypes.byref(arr(*seq)), ctypes.sizeof(INPUT))


def send_vk(vk: int) -> None:
    """发送一个虚拟键（用于回车等）。"""
    arr = INPUT * 2
    user32.SendInput(
        2,
        ctypes.byref(arr(_kb_input(vk, 0, 0), _kb_input(vk, 0, KEYEVENTF_KEYUP))),
        ctypes.sizeof(INPUT),
    )


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def virtual_screen_bounds() -> tuple[int, int, int, int]:
    """返回所有显示器组成的虚拟屏幕区域 (x, y, width, height)。"""
    try:
        gsm = user32.GetSystemMetrics
        return gsm(76), gsm(77), gsm(78), gsm(79)  # X/Y/CX/CY_VIRTUALSCREEN
    except Exception:
        return 0, 0, 0, 0


def send_ctrl_key(vk: int) -> None:
    """发送 Ctrl+某键（用于自动化测试里的全选 / 复制）。"""
    arr = INPUT * 4
    user32.SendInput(
        4,
        ctypes.byref(arr(
            _kb_input(VK_CONTROL, 0, 0),
            _kb_input(vk, 0, 0),
            _kb_input(vk, 0, KEYEVENTF_KEYUP),
            _kb_input(VK_CONTROL, 0, KEYEVENTF_KEYUP),
        )),
        ctypes.sizeof(INPUT),
    )


def find_window_for_pid(pid: int):
    """找出某个进程的主窗口句柄。"""
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        wnd_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
        if wnd_pid.value == pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left > 200 and rect.bottom - rect.top > 150:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def clipboard_text() -> str:
    """读取剪贴板中的 Unicode 文本。"""
    CF_UNICODETEXT = 13
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------------------------- #
# 文本预处理（与原版行为一致）
# --------------------------------------------------------------------------- #
def clean_markdown(text: str) -> str:
    """去除从 Markdown 内容里复制出来的格式符号（** * __ ~~ ` # > 列表符等），保留正文。"""
    text = re.sub(r"^[ \t]*```[^\n]*\n?", "", text, flags=re.M)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)

    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"(?<![A-Za-z0-9])_([^_\n]+)_(?![A-Za-z0-9])", r"\1", text)

    text = re.sub(r"~~([^~]+)~~", r"\1", text)

    text = re.sub(r"`+([^`\n]+)`+", r"\1", text)

    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", text)
    text = re.sub(r"(?m)^[ \t]{0,3}>[ \t]?", "", text)
    text = re.sub(r"(?m)^[ \t]*[-*+][ \t]+", "", text)

    text = re.sub(r"(?m)^[ \t]*([-*_])\1{2,}[ \t]*$", "", text)
    return text


def fix_list_numbering(text: str) -> str:
    """适配在线编辑器的自动编号列表：
    - 把单独成行的“1.”与下一行标题合并；
    - 每组列表保留第一个“1.”（用于触发自动列表），去掉后续“2. 3. …”（编辑器会自动生成）。
    """
    text = re.sub(r"(?m)^([ \t]*)(\d+)[.、)][ \t]*\r?\n", r"\1\2. ", text)

    num_re = re.compile(r"^([ \t]*)(\d+)[.、)][ \t]+(.*\S.*)$")
    in_list = False
    expect = 2
    out = []
    for line in text.split("\n"):
        m = num_re.match(line)
        if m:
            indent, num_str, body = m.group(1), int(m.group(2)), m.group(3)
            if not in_list:
                if num_str == 1:
                    in_list, expect = True, 2
                out.append(line)
                continue
            if num_str == expect:
                out.append(indent + body)
                expect += 1
                continue
            if num_str == 1:
                in_list, expect = True, 2
                out.append(line)
                continue
            in_list = False
            out.append(line)
            continue

        if in_list and line.strip():
        # 列表结束：先让编辑器退出自动编号，再继续输入正文
            out.append(EXIT_SENTINEL + line)
            in_list = False
            continue
        out.append(line)
    return "\n".join(out)


def strip_blank_lines(text: str) -> str:
    """删除所有空白行，段落之间仅保留换行。"""
    return "\n".join(ln for ln in text.split("\n") if ln.strip())


def effective_length(content: str, newline_mode: str) -> int:
    """按换行处理方式统计实际会输入的字符数（跳过 \\r 与控制指令）。"""
    lines = content.split("\n")
    n = 0
    for idx, raw in enumerate(lines):
        line = raw.replace("\r", "")
        if line.startswith(EXIT_SENTINEL):
            line = line[len(EXIT_SENTINEL):]
        n += len(line)
        if idx < len(lines) - 1 and newline_mode in ("转为空格", "发送回车"):
            n += 1
    return n


def preprocess_text(content: str, *, markdown: bool, blank_lines: bool, list_fix: bool) -> str:
    if markdown:
        content = clean_markdown(content)
    if blank_lines:
        content = strip_blank_lines(content)
    if list_fix:
        content = fix_list_numbering(content)
    return content


# --------------------------------------------------------------------------- #
# 视觉主题
# --------------------------------------------------------------------------- #
class C:
    BG = "#F2F5FA"
    CARD = "#FFFFFF"
    CARD_SOFT = "#F7F9FD"
    BORDER = "#E3E8F2"
    BORDER_STRONG = "#D3DBEA"
    TEXT = "#0F172A"
    TEXT_SOFT = "#475569"
    MUTED = "#7C8AA0"
    PRIMARY = "#3B6FF6"
    PRIMARY_HOVER = "#2F61E6"
    PRIMARY_ACTIVE = "#2755CC"
    PRIMARY_SOFT = "#E8EFFF"
    SUCCESS = "#10B981"
    SUCCESS_SOFT = "#E6F7F1"
    DANGER = "#EF4444"
    DANGER_HOVER = "#E03B3B"
    DANGER_ACTIVE = "#C93030"
    DANGER_SOFT = "#FDECEC"
    WARN = "#F59E0B"
    TRACK = "#E9EEF8"
    DISABLED_BG = "#EDF1F7"
    DISABLED_FG = "#A9B4C6"
    CONSOLE_BG = "#0E1526"
    CONSOLE_FG = "#C7D2E4"
    CONSOLE_MUTED = "#5C6B85"
    CONSOLE_OK = "#4ADE80"
    CONSOLE_WARN = "#FBBF24"
    CONSOLE_ERR = "#F87171"


UI = "Microsoft YaHei UI"
MONO = "Consolas"

# 界面缩放系数：由 enable_dpi_awareness() 在创建窗口前赋值
SCALE = 1.0


def px(value: float) -> int:
    """把设计稿上的像素值换算成当前 DPI 下的真实像素值。"""
    return max(1, int(round(value * SCALE)))


def resource_path(name: str) -> str:
    """返回随程序一起打包的资源的绝对路径（兼容 PyInstaller 单文件模式）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def set_app_icon(root: tk.Tk) -> None:
    """设置窗口与任务栏图标。"""
    for name in ("app.ico", "icon.ico"):
        path = resource_path(name)
        if os.path.exists(path):
            try:
                root.iconbitmap(default=path)
                return
            except Exception:
                continue


def font(size: int = 10, weight: str = "normal", family: str = UI) -> tuple:
    return (family, size, weight) if weight != "normal" else (family, size)


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形（用平滑多边形模拟）。"""
    r = max(0, min(r, abs(x2 - x1) / 2, abs(y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def parent_bg(widget) -> str:
    try:
        return widget.cget("bg")
    except Exception:
        try:
            return widget.cget("background")
        except Exception:
            return C.BG


# --------------------------------------------------------------------------- #
# 自定义控件
# --------------------------------------------------------------------------- #
class RoundedBox(tk.Canvas):
    """圆角卡片容器：把子控件放进 ``self.body``。"""

    def __init__(self, master, *, radius=16, fill=C.CARD, border=C.BORDER,
                 pad=18, shadow=True, auto_height=True, height=None, **kw):
        kw.pop("bg", None)
        super().__init__(master, highlightthickness=0, bd=0, bg=parent_bg(master),
                         width=px(120), height=px(60), **kw)
        self._radius, self._fill, self._border = radius, fill, border
        self._radius = px(radius)
        self._pad, self._shadow = px(pad), shadow
        self._auto_height = auto_height
        if height:
            self.configure(height=px(height))
        self.body = tk.Frame(self, bg=fill)
        self._win = None
        self.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._sync_height)

    def _sync_height(self, _event=None):
        if not self._auto_height:
            return
        need = self.body.winfo_reqheight() + 2 * self._pad
        try:
            current = int(float(self["height"]))
        except Exception:
            current = -1
        if abs(current - need) > 1:
            self.configure(height=need)

    def _redraw(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2 or h <= 2:
            return
        self.delete("bg")
        r = self._radius
        if self._shadow:
            round_rect(self, px(3), px(4), w - 1, h - 1, r,
                       fill="#E4E9F3", outline="", tags="bg")
            round_rect(self, px(2), px(3), w - 2, h - 2, r,
                       fill="#EDF1F8", outline="", tags="bg")
        round_rect(self, 1, 1, w - 1, h - 1, r, fill=self._fill,
                   outline=self._border, width=1, tags="bg")
        self.tag_lower("bg")
        p = self._pad
        iw, ih = max(1, w - 2 * p), max(1, h - 2 * p)
        if self._win is None:
            if self._auto_height:
                self._win = self.create_window(p, p, anchor="nw", window=self.body,
                                               width=iw)
            else:
                self._win = self.create_window(p, p, anchor="nw", window=self.body,
                                               width=iw, height=ih)
        else:
            if self._auto_height:
                self.itemconfigure(self._win, width=iw)
            else:
                self.itemconfigure(self._win, width=iw, height=ih)
            self.coords(self._win, p, p)


class RoundButton(tk.Canvas):
    """圆角扁平按钮，自带悬停 / 按下 / 禁用状态。"""

    VARIANTS = {
        "primary": dict(fill=C.PRIMARY, hover=C.PRIMARY_HOVER, active=C.PRIMARY_ACTIVE,
                        fg="#FFFFFF", border=""),
        "secondary": dict(fill="#FFFFFF", hover="#F3F6FC", active="#E9EFFA",
                          fg=C.TEXT, border=C.BORDER_STRONG),
        "ghost": dict(fill="__parent__", hover="#EEF2FA", active="#E4EAF6",
                      fg=C.TEXT_SOFT, border=""),
        "danger": dict(fill=C.DANGER, hover=C.DANGER_HOVER, active=C.DANGER_ACTIVE,
                       fg="#FFFFFF", border=""),
        "soft": dict(fill=C.PRIMARY_SOFT, hover="#DCE7FF", active="#CFDDFF",
                     fg=C.PRIMARY, border=""),
        "quiet": dict(fill="#F3F6FC", hover="#E8EEF9", active="#DEE6F4",
                      fg=C.TEXT_SOFT, border=""),
    }

    def __init__(self, master, text="", command=None, *, variant="secondary",
                 width=None, height=40, radius=None, font_spec=None, glyph="",
                 pad_x=20, **kw):
        self._variant = self.VARIANTS.get(variant, self.VARIANTS["secondary"])
        user_bg = kw.pop("bg", None) or parent_bg(master)
        self._base_bg = user_bg if self._variant["fill"] == "__parent__" else None
        super().__init__(master, highlightthickness=0, bd=0, bg=user_bg,
                         takefocus=1, **kw)
        self._text = text
        self._glyph = glyph
        self._command = command
        self._radius = radius if radius is not None else height // 2
        self._font = font_spec or font(10, "bold")
        self._radius = px(self._radius)
        self._pad_x = px(pad_x)
        self._state = "normal"
        self._hover = False
        self._pressed = False

        if width is None:
            width = max(96, (self._measure() + px(pad_x) * 2) / max(SCALE, 0.1))
        self.configure(width=px(width), height=px(height), cursor="hand2")
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._redraw())
        self.bind("<FocusOut>", lambda e: self._redraw())

    # -- helpers ---------------------------------------------------------- #
    def _label(self) -> str:
        return f"{self._glyph}  {self._text}" if self._glyph else self._text

    def _measure(self) -> int:
        f = tkfont.Font(font=self._font)
        return f.measure(self._label())

    def _colors(self):
        v = self._variant
        if self._state == "disabled":
            return C.DISABLED_BG, C.DISABLED_FG, ""
        fill = v["fill"]
        if fill == "__parent__":
            fill = self._base_bg
        if self._pressed:
            fill = v["active"]
        elif self._hover:
            fill = v["hover"]
        return fill, v["fg"], v["border"]

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2 or h <= 2:
            return
        fill, fg, border = self._colors()
        round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=fill,
                   outline=border or fill, width=1)
        if self.focus_get() is self:
            round_rect(self, 3, 3, w - 3, h - 3, max(2, self._radius - 2),
                       fill="", outline=C.PRIMARY, width=1)
        self.create_text(w / 2, h / 2 + 1, text=self._label(), fill=fg,
                         font=self._font, anchor="center")

    # -- events ----------------------------------------------------------- #
    def _on_enter(self, _e=None):
        if self._state == "disabled":
            return
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = self._pressed = False
        self._redraw()

    def _on_press(self, _e=None):
        if self._state == "disabled":
            return
        self.focus_set()
        self._pressed = True
        self._redraw()

    def _on_release(self, event=None):
        if self._state == "disabled":
            return
        was = self._pressed
        self._pressed = False
        self._redraw()
        if was and event is not None:
            if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
                self.invoke()

    # -- public API ------------------------------------------------------- #
    def invoke(self):
        if self._state != "disabled" and self._command:
            self._command()

    def set_state(self, state: str):
        self._state = "disabled" if state == "disabled" else "normal"
        self.configure(cursor="arrow" if self._state == "disabled" else "hand2")
        self._hover = self._pressed = False
        self._redraw()

    def set_text(self, text: str):
        self._text = text
        self._redraw()

    def set_variant(self, variant: str):
        self._variant = self.VARIANTS.get(variant, self.VARIANTS["secondary"])
        self._redraw()


class ToggleSwitch(tk.Frame):
    """现代开关（带标题与说明文字）。"""

    def __init__(self, master, text, variable, *, desc=None, command=None,
                 bg=C.CARD, switch_w=42, switch_h=24):
        super().__init__(master, bg=bg)
        self.var = variable
        self._command = command
        self._bg = bg
        self._sw, self._sh = px(switch_w), px(switch_h)
        self._knob_x = 1.0 if variable.get() else 0.0
        self._anim = None

        self.canvas = tk.Canvas(self, width=self._sw, height=self._sh, bg=bg,
                                highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(side="left", anchor="n")

        box = tk.Frame(self, bg=bg)
        box.pack(side="left", padx=(px(9), 0), anchor="n")
        self.label = tk.Label(box, text=text, bg=bg, fg=C.TEXT, font=font(10),
                              anchor="w", cursor="hand2")
        self.label.pack(anchor="w")
        if desc:
            self.desc = tk.Label(box, text=desc, bg=bg, fg=C.MUTED, font=font(9),
                                 anchor="w", justify="left", cursor="hand2")
            self.desc.pack(anchor="w", pady=(px(1), 0))
        else:
            self.desc = None

        for w in (self.canvas, self.label, self.desc):
            if w is not None:
                w.bind("<Button-1>", lambda e: self.toggle())
        self._draw()

    # ------------------------------------------------------------------ #
    def _draw(self):
        cv = self.canvas
        cv.delete("all")
        w, h = self._sw, self._sh
        pos = self._knob_x
        if self.var.get():
            fill = C.PRIMARY if pos > 0.5 else C._mix(C.DISABLED_BG, C.PRIMARY, pos * 2)
        else:
            fill = C.DISABLED_BG if pos < 0.5 else C._mix(C.PRIMARY, C.DISABLED_BG, 1 - pos * 2)
        round_rect(cv, 0.5, 0.5, w - 0.5, h - 0.5, h / 2, fill=fill, outline=fill)
        pad = px(3)
        d = h - pad * 2
        x0 = pad + pos * (w - d - pad * 2)
        cv.create_oval(x0 + px(1), pad + px(1.5), x0 + d + px(1), pad + d + px(1.5),
                       fill="#D9E0EC", outline="")
        cv.create_oval(x0, pad, x0 + d, pad + d, fill="#FFFFFF", outline="")

    def _animate(self, target):
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
        step = 0.18 if target > self._knob_x else -0.18

        def tick():
            self._knob_x += step
            if (step > 0 and self._knob_x >= target) or (step < 0 and self._knob_x <= target):
                self._knob_x = target
                self._anim = None
            else:
                self._anim = self.after(12, tick)
            self._draw()

        tick()

    def toggle(self):
        self.var.set(not self.var.get())
        self._animate(1.0 if self.var.get() else 0.0)
        if self._command:
            self._command()

    def set(self, value: bool):
        self.var.set(bool(value))
        self._knob_x = 1.0 if value else 0.0
        self._draw()


def _mix(c1: str, c2: str, t: float) -> str:
    """在两个 #RRGGBB 颜色之间线性插值，t=0 取 c1。"""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


C._mix = staticmethod(_mix)


class Segmented(tk.Canvas):
    """分段选择控件。"""

    def __init__(self, master, options, variable, *, command=None, height=36,
                 font_spec=None, pad_x=16, bg=C.CARD):
        super().__init__(master, highlightthickness=0, bd=0, bg=bg,
                         height=px(height), cursor="hand2")
        self._items = list(options)
        self._var = variable
        self._command = command
        self._font = font_spec or font(10)
        self._pad_x = px(pad_x)
        self._h = px(height)
        self._hover_idx = -1
        self._widths = []
        self._redraw()
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    def _measure(self):
        f = tkfont.Font(font=self._font)
        self._widths = [f.measure(str(o)) + self._pad_x * 2 for o in self._items]
        return sum(self._widths)

    def _redraw(self):
        self.delete("all")
        total = self._measure()
        h = self._h
        w = max(total + px(8), self.winfo_width() if self.winfo_width() > 1 else total + px(8))
        self.configure(width=total + px(8))
        round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, h / 2,
                   fill=C.TRACK, outline=C.TRACK)
        try:
            current = str(self._var.get())
        except Exception:
            current = ""
        x = px(4)
        for idx, opt in enumerate(self._items):
            seg_w = self._widths[idx]
            selected = str(opt) == current
            if selected:
                round_rect(self, x, px(3), x + seg_w, h - px(3), (h - px(6)) / 2,
                           fill="#FFFFFF", outline=C.BORDER_STRONG)
            color = C.PRIMARY if selected else (
                C.TEXT_SOFT if idx == self._hover_idx else C.MUTED)
            f = tkfont.Font(font=self._font if not selected else font(10, "bold"))
            self.create_text(x + seg_w / 2, h / 2 + 1, text=str(opt), fill=color, font=f)
            x += seg_w

    def _idx_at(self, x):
        pos = px(4)
        for idx, seg_w in enumerate(self._widths):
            if pos <= x <= pos + seg_w:
                return idx
            pos += seg_w
        return -1

    def _on_motion(self, event):
        idx = self._idx_at(event.x)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self._redraw()

    def _on_leave(self, _e=None):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self._redraw()

    def _on_click(self, event):
        idx = self._idx_at(event.x)
        if idx < 0:
            return
        self._var.set(self._items[idx])
        self._redraw()
        if self._command:
            self._command(self._items[idx])


class SlimProgress(tk.Canvas):
    """细长的圆角进度条，带平滑动画。"""

    def __init__(self, master, *, height=10, bg=C.CARD, fill=C.PRIMARY,
                 track=C.TRACK, **kw):
        super().__init__(master, height=px(height), highlightthickness=0, bd=0,
                         bg=bg, **kw)
        self._h = px(height)
        self._fill_color = fill
        self._track = track
        self._value = 0.0
        self._shown = 0.0
        self._anim = None
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, fraction: float, animate=True):
        self._value = max(0.0, min(1.0, float(fraction)))
        if not animate:
            self._shown = self._value
            self._draw()
            return
        if self._anim is None:
            self._tick()

    def reset(self):
        self._value = self._shown = 0.0
        self._draw()

    def _tick(self):
        diff = self._value - self._shown
        if abs(diff) < 0.004:
            self._shown = self._value
            self._draw()
            self._anim = None
            return
        self._shown += diff * 0.28
        self._draw()
        self._anim = self.after(16, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self._h
        if w <= 2:
            return
        r = h / 2
        round_rect(self, 0, 0, w, h, r, fill=self._track, outline=self._track)
        fw = self._shown * w
        if fw >= 2:
            round_rect(self, 0, 0, max(fw, h), h, r,
                       fill=self._fill_color, outline=self._fill_color)


class CountRing(tk.Canvas):
    """倒计时圆环。"""

    def __init__(self, master, size=44, bg=C.CARD):
        super().__init__(master, width=px(size), height=px(size), bg=bg,
                         highlightthickness=0, bd=0)
        self._size = px(size)
        self._value = 0
        self._total = 1
        self._draw()

    def set(self, value: int, total: int):
        self._value, self._total = value, max(1, total)
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self._size
        pad = px(3)
        self.create_oval(pad, pad, s - pad, s - pad, outline=C.TRACK, width=px(4))
        if self._value > 0:
            extent = 360.0 * (self._value / self._total)
            self.create_arc(pad, pad, s - pad, s - pad, start=90, extent=-extent,
                            style="arc", outline=C.PRIMARY, width=px(4))
            self.create_text(s / 2, s / 2 + 1, text=str(self._value),
                             fill=C.PRIMARY, font=font(12, "bold", MONO))
        else:
            self.create_text(s / 2, s / 2 + 1, text="✓", fill=C.SUCCESS,
                             font=font(13, "bold"))


class SlimSlider(tk.Canvas):
    """圆角滑块，用于精细调节每字延迟。"""

    def __init__(self, master, variable: tk.IntVar, *, from_=0, to=200,
                 command=None, width=240, height=28, bg=C.CARD):
        super().__init__(master, width=px(width), height=px(height), bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._var = variable
        self._from, self._to = from_, to
        self._command = command
        self._h = px(height)
        self._dragging = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _track(self):
        w = self.winfo_width() or int(self["width"])
        return px(12), w - px(12), self._h / 2

    def _knob_x(self):
        x0, x1, _ = self._track()
        frac = (self._var.get() - self._from) / max(1, (self._to - self._from))
        frac = max(0.0, min(1.0, frac))
        return x0 + frac * (x1 - x0)

    def _draw(self):
        self.delete("all")
        x0, x1, cy = self._track()
        round_rect(self, x0, cy - px(3), x1, cy + px(3), px(3),
                   fill=C.TRACK, outline=C.TRACK)
        kx = self._knob_x()
        if kx > x0:
            round_rect(self, x0, cy - px(3), kx, cy + px(3), px(3),
                       fill=C.PRIMARY, outline=C.PRIMARY)
        r = px(8)
        self.create_oval(kx - r, cy - r + px(1.5), kx + r, cy + r + px(1.5),
                         fill="#D6DEEE", outline="")
        self.create_oval(kx - r, cy - r, kx + r, cy + r,
                         fill="#FFFFFF", outline=C.PRIMARY, width=2)

    def _set_from_x(self, x):
        x0, x1, _ = self._track()
        frac = (x - x0) / max(1, (x1 - x0))
        frac = max(0.0, min(1.0, frac))
        value = round(self._from + frac * (self._to - self._from))
        if value != self._var.get():
            self._var.set(value)
            self._draw()
            if self._command:
                self._command(value)

    def _on_press(self, event):
        self._dragging = True
        self._set_from_x(event.x)

    def _on_drag(self, event):
        if self._dragging:
            self._set_from_x(event.x)

    def _on_release(self, _event):
        self._dragging = False
        self._draw()


class Stepper(tk.Frame):
    """[- 3 +] 形式的紧凑数字调节器。"""

    def __init__(self, master, variable: tk.IntVar, *, from_=0, to=99,
                 bg=C.CARD, width=104):
        super().__init__(master, bg=bg)
        self.var = variable
        self._from, self._to = from_, to
        self._bg = bg
        self._entry_var = tk.StringVar(value=str(variable.get()))

        self.btn_minus = RoundButton(self, "−", lambda: self.step(-1), variant="soft",
                                     width=30, height=30, radius=9,
                                     font_spec=font(12, "bold"), bg=bg, pad_x=0)
        self.btn_minus.pack(side="left")

        self.entry = tk.Entry(self, textvariable=self._entry_var, width=4,
                              justify="center", relief="flat", bg=bg, fg=C.TEXT,
                              font=font(11, "bold", MONO), insertbackground=C.PRIMARY,
                              highlightthickness=0, bd=0)
        self.entry.pack(side="left", padx=2)
        self.entry.bind("<FocusOut>", lambda _e: self.sync())
        self.entry.bind("<Return>", lambda _e: self.sync())

        self.btn_plus = RoundButton(self, "+", lambda: self.step(1), variant="soft",
                                    width=30, height=30, radius=9,
                                    font_spec=font(12, "bold"), bg=bg, pad_x=0)
        self.btn_plus.pack(side="left")
        self.configure(width=px(width))

    def step(self, delta: int):
        value = max(self._from, min(self._to, self.var.get() + delta))
        self.var.set(value)
        self._entry_var.set(str(value))

    def sync(self):
        if self._entry_var.get().strip() != str(self.var.get()):
            self._entry_var.set(str(self.var.get()))


# --------------------------------------------------------------------------- #
# 主程序
# --------------------------------------------------------------------------- #
class AutoTypeApp:
    NEWLINE_OPTIONS = ("跳过换行", "转为空格", "发送回车")
    SPEED_PRESETS = (("慢", 120), ("标准", 60), ("快", 25), ("极速", 5))
    DEMO_TEXT = (
        "1. 第一点：要录入的内容可以直接整段粘贴到这里。\n"
        "2. 第二点：也可以写完 Markdown 再让助手自动去掉 # 、** 等符号。\n"
        "3. 第三点：把光标点进目标输入框，按 F9 就会逐字输入。\n"
        "\n"
        "输入速度、换行方式都可以在下方调节；F8 可以随时重新开始。"
    )

    def __init__(self, root: tk.Tk, scale: float = 1.0):
        self.root = root
        self.scale = scale
        self.stop_event = threading.Event()
        self.worker = None
        self.ui_queue = queue.Queue()
        self.prev_f8 = False
        self.prev_f9 = False
        self.log_expanded = False
        self._running = False
        self._started_at = 0.0
        self._save_job = None

        cfg = self._load_settings()
        self.countdown_var = tk.IntVar(value=int(cfg.get("countdown", 2)))
        self.delay_var = tk.IntVar(value=int(cfg.get("delay", 10)))
        self.newline_var = tk.StringVar(value=cfg.get("newline", "发送回车"))
        self.jitter_var = tk.BooleanVar(value=bool(cfg.get("jitter", True)))
        self.topmost_var = tk.BooleanVar(value=bool(cfg.get("topmost", True)))
        self.clean_md_var = tk.BooleanVar(value=bool(cfg.get("clean_md", True)))
        self.fix_list_var = tk.BooleanVar(value=bool(cfg.get("fix_list", True)))
        self.rm_blank_var = tk.BooleanVar(value=bool(cfg.get("rm_blank", True)))
        self.speed_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.percent_var = tk.StringVar(value="0%")
        self.eta_var = tk.StringVar(value="等待开始")

        self._build_ui(cfg)
        self._sync_speed_preset()
        self._update_stats()
        self._apply_topmost()
        if self.log_expanded:
            self.root.after(120, self._resize_for_log)
        self._poll_queue()
        self._poll_hotkeys()

    # ------------------------------------------------------------------ #
    # 设置存取
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_settings() -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings(self, *_):
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(500, self._write_settings)

    def _write_settings(self):
        self._save_job = None
        data = {
            "countdown": self.countdown_var.get(),
            "delay": self.delay_var.get(),
            "newline": self.newline_var.get(),
            "jitter": bool(self.jitter_var.get()),
            "topmost": bool(self.topmost_var.get()),
            "clean_md": bool(self.clean_md_var.get()),
            "fix_list": bool(self.fix_list_var.get()),
            "rm_blank": bool(self.rm_blank_var.get()),
            "log_expanded": bool(self.log_expanded),
            "mini": bool(getattr(self, "_mini", False)),
            "geometry": [self.root.winfo_x(), self.root.winfo_y(),
                         self.root.winfo_width(), self.root.winfo_height()],
        }
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #
    def _build_ui(self, cfg: dict):
        root = self.root
        root.configure(bg=C.BG)
        root.title(APP_TITLE)

        # 允许自由缩放：下限放到 380×260（逻辑像素），窄窗口会自动切换紧凑布局
        min_w, min_h = int(380 * self.scale), int(260 * self.scale)
        root.minsize(min_w, min_h)

        vx, vy, vw, vh = virtual_screen_bounds()
        if vw <= 0 or vh <= 0:
            vx, vy = 0, 0
            vw, vh = root.winfo_screenwidth(), root.winfo_screenheight()

        geo = cfg.get("geometry")
        if isinstance(geo, list) and len(geo) == 4:
            # 恢复上次的窗口位置/大小，但夹在可见屏幕范围内（防止出现在屏幕外拖动不到）
            w = min(max(min_w, int(geo[2])), vw)
            h = min(max(min_h, int(geo[3])), vh)
            x = min(max(int(geo[0]), vx), max(vx, vx + vw - w))
            y = min(max(int(geo[1]), vy), max(vy, vy + vh - h))
            root.geometry(f"{w}x{h}+{x}+{y}")
        else:
            # 默认就是个"小面板"：1080p 屏幕上约占 32% × 48%
            w, h = int(620 * self.scale), int(520 * self.scale)
            w, h = min(w, vw - int(60 * self.scale)), min(h, vh - int(90 * self.scale))
            root.geometry(f"{w}x{h}+{max(vx, vx + (vw - w) // 2)}+{max(vy, vy + (vh - h) // 2 - 20)}")

        self._compact = None
        root.bind("<Configure>", self._on_root_configure)
        # 关闭尺寸传播：否则重新排布控件时 Tk 会把窗口"弹回"它自己算出的尺寸，
        # 用户就没法把窗口拖到想要的大小（内容改用滚动来适配）
        root.pack_propagate(False)

        # 滚动容器：窗口缩得比内容还小时可以滚动，保证所有控件都能用
        scroll_host = tk.Frame(root, bg=C.BG)
        scroll_host.pack(fill="both", expand=True)
        self._scroll_canvas = tk.Canvas(scroll_host, bg=C.BG, highlightthickness=0, bd=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar = ttk.Scrollbar(scroll_host, orient="vertical",
                                       command=self._scroll_canvas.yview,
                                       style="Slim.Vertical.TScrollbar")
        self._scroll_canvas.configure(yscrollcommand=self._on_scroll_set)

        outer = tk.Frame(self._scroll_canvas, bg=C.BG, padx=px(14), pady=px(12))
        self._outer_window = self._scroll_canvas.create_window(0, 0, anchor="nw", window=outer)
        outer.bind("<Configure>", lambda _e: self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.bind("<Configure>", lambda e: self._scroll_canvas.itemconfigure(
            self._outer_window, width=e.width))
        root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1, minsize=px(150))
        self._outer = outer

        self._build_header(outer)     # row 0
        self._build_editor(outer)     # row 1（会随窗口伸展）
        self._build_actions(outer)    # row 2
        self._build_progress(outer)   # row 3
        self._build_settings(outer)   # row 4（小窗口时可滚动查看）
        self._build_log(outer)        # row 5

        self.log_expanded = bool(cfg.get("log_expanded", False))
        if self.log_expanded:
            self.log_body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
            self.log_header_btn.set_text("▾  运行日志")

        self._mini = bool(cfg.get("mini", False))
        self._pre_mini_geometry = None
        if self._mini:
            self.root.after(80, self._apply_mini)

        self._build_context_menus()

    # -- 顶部标题 ------------------------------------------------------- #
    def _build_header(self, parent):
        head = tk.Frame(parent, bg=C.BG)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        head.columnconfigure(0, weight=1)

        left = tk.Frame(head, bg=C.BG)
        left.grid(row=0, column=0, sticky="w")
        title_row = tk.Frame(left, bg=C.BG)
        title_row.pack(anchor="w")
        tk.Label(title_row, text=APP_NAME, bg=C.BG, fg=C.TEXT,
                 font=font(17, "bold")).pack(side="left")
        self._version_label = tk.Label(title_row, text=f"v{APP_VERSION}", bg=C.BG, fg=C.PRIMARY,
                                       font=font(9, "bold"))
        self._version_label.pack(side="left", padx=(8, 0), pady=(6, 0))
        self._author_label = tk.Label(title_row, text=f"by {APP_AUTHOR}", bg=C.BG, fg=C.MUTED,
                                      font=font(9))
        self._author_label.pack(side="left", padx=(6, 0), pady=(6, 0))
        self.subtitle_label = tk.Label(
            left,
            text="把光标点进目标输入框 → 按 F9 开始逐字输入   ·   F8 重新开始   ·   Esc 紧急停止",
            bg=C.BG, fg=C.MUTED, font=font(9))
        self.subtitle_label.pack(anchor="w", pady=(3, 0))

        right = tk.Frame(head, bg=C.BG)
        right.grid(row=0, column=1, sticky="e")
        self.mini_btn = RoundButton(right, "迷你模式", self.toggle_mini, variant="quiet",
                                    height=34, radius=10, font_spec=font(9), pad_x=12,
                                    width=104, bg=C.BG)
        self.mini_btn.pack(side="left", padx=(0, 8))
        ToggleSwitch(right, "窗口置顶", self.topmost_var, bg=C.BG,
                     command=self._on_topmost_toggle,
                     switch_w=38, switch_h=22).pack(side="left")
        self._help_btn = RoundButton(right, "使用说明", self.show_help, variant="quiet", height=34,
                                     radius=10, font_spec=font(9), glyph="?", width=104, bg=C.BG)
        self._help_btn.pack(side="left", padx=(10, 0))

    # -- 文本编辑区 ----------------------------------------------------- #
    def _build_editor(self, parent):
        card = RoundedBox(parent, radius=18, pad=16, shadow=True,
                          auto_height=False, height=190)
        card.grid(row=1, column=0, sticky="nsew")
        self._card_editor = card
        body = card.body
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        bar = tk.Frame(body, bg=C.CARD)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.columnconfigure(0, weight=1)

        title = tk.Frame(bar, bg=C.CARD)
        title.grid(row=0, column=0, sticky="w")
        tk.Label(title, text="要输入的内容", bg=C.CARD, fg=C.TEXT,
                 font=font(11, "bold")).pack(side="left")
        self.editor_hint = tk.Label(title, text="支持 Markdown，可直接粘贴", bg=C.CARD,
                                    fg=C.MUTED, font=font(9))
        self.editor_hint.pack(side="left", padx=(8, 0))

        tools = tk.Frame(bar, bg=C.CARD)
        tools.grid(row=0, column=1, sticky="e")
        self._tool_buttons = []
        for text, cmd in (("导入", self.import_text), ("导出", self.export_text),
                          ("示例", self.insert_sample), ("清空", self.clear_text)):
            btn = RoundButton(tools, text, cmd, variant="quiet", height=30, radius=9,
                              font_spec=font(9), pad_x=12, bg=C.CARD)
            btn.pack(side="left", padx=(6, 0))
            btn._wide_width = btn.winfo_reqwidth()
            self._tool_buttons.append(btn)

        wrap = tk.Frame(body, bg=C.CARD, highlightthickness=1,
                        highlightbackground=C.BORDER, highlightcolor=C.PRIMARY)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.text_wrap = wrap
        self.text_input = tk.Text(
            wrap, wrap="word", undo=True, relief="flat", bd=0,
            bg=C.CARD, fg=C.TEXT, insertbackground=C.PRIMARY,
            selectbackground="#CFE0FF", selectforeground=C.TEXT,
            font=font(11), padx=px(14), pady=px(12),
            spacing1=px(2), spacing3=px(3),
            highlightthickness=0,
        )
        self.text_input.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.text_input.yview,
                           style="Slim.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns")
        self.text_input.configure(yscrollcommand=sb.set)
        self.text_input.bind("<<Modified>>", self._on_text_modified)
        self.text_input.bind("<Control-Return>", self._on_ctrl_enter)
        self.text_input.bind("<Control-v>", lambda _e: (self.paste_text(), "break")[1])
        self.text_input.bind("<Control-c>", lambda _e: (self.copy_text(), "break")[1])
        self.text_input.bind("<Control-x>", lambda _e: (self.cut_text(), "break")[1])

        stats = tk.Frame(body, bg=C.CARD)
        stats.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        stats.columnconfigure(0, weight=1)
        self.stats_left = tk.Label(stats, text="共 0 字 · 0 行 · 预计 0.0 秒",
                                   bg=C.CARD, fg=C.MUTED, font=font(9))
        self.stats_left.grid(row=0, column=0, sticky="w")
        self.stats_right = tk.Label(stats, text="换行：发送回车", bg=C.CARD,
                                    fg=C.MUTED, font=font(9))
        self.stats_right.grid(row=0, column=1, sticky="e")

    # -- 输入设置 ------------------------------------------------------- #
    def _build_settings(self, parent):
        card = RoundedBox(parent, radius=18, pad=14)
        card.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._card_settings = card
        body = card.body
        body.columnconfigure(0, weight=1)

        row1 = tk.Frame(body, bg=C.CARD)
        row1.grid(row=0, column=0, sticky="ew")
        tk.Label(row1, text="输入速度", bg=C.CARD, fg=C.TEXT,
                 font=font(10, "bold")).pack(side="left")

        self.speed_seg = Segmented(row1, [name for name, _ in self.SPEED_PRESETS],
                                   self.speed_var, command=self._on_speed_preset,
                                   height=34, font_spec=font(9), pad_x=13)
        self.speed_seg.pack(side="left", padx=(12, 16))

        self.delay_slider = SlimSlider(row1, self.delay_var, from_=0, to=200,
                                       command=self._on_delay_changed, width=240)
        self.delay_slider.pack(side="left")

        self.delay_label = tk.Label(row1, text="10 毫秒/字", bg=C.CARD, fg=C.PRIMARY,
                                    font=font(9, "bold"), width=12, anchor="w")
        self.delay_label.pack(side="left", padx=(12, 0))

        row2 = tk.Frame(body, bg=C.CARD)
        row2.grid(row=1, column=0, sticky="ew", pady=(14, 0))

        tk.Label(row2, text="开始倒计时", bg=C.CARD, fg=C.TEXT,
                 font=font(10, "bold")).pack(side="left")
        self.stepper = Stepper(row2, self.countdown_var, from_=0, to=30)
        self.stepper.pack(side="left", padx=(10, 4))
        tk.Label(row2, text="秒", bg=C.CARD, fg=C.MUTED, font=font(9)).pack(side="left")

        tk.Label(row2, text="换行处理", bg=C.CARD, fg=C.TEXT,
                 font=font(10, "bold")).pack(side="left", padx=(26, 0))
        self.newline_seg = Segmented(row2, self.NEWLINE_OPTIONS, self.newline_var,
                                     command=lambda _v: self._on_option_changed(),
                                     height=34, font_spec=font(9), pad_x=13)
        self.newline_seg.pack(side="left", padx=(12, 0))

        row3 = tk.Frame(body, bg=C.CARD)
        row3.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.jitter_switch = ToggleSwitch(row3, "模拟真人速度抖动", self.jitter_var,
                                          desc="在设定速度上做 ±30% 随机浮动，更像真人打字",
                                          command=self._save_settings)
        self.jitter_switch.pack(side="left")

        divider = tk.Frame(body, bg=C.BORDER, height=1)
        divider.grid(row=3, column=0, sticky="ew", pady=(14, 0))

        row4 = tk.Frame(body, bg=C.CARD)
        row4.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self._cleanup_row = row4
        self._cleanup_label = tk.Label(row4, text="文本整理", bg=C.CARD, fg=C.TEXT,
                                       font=font(10, "bold"))
        self._cleanup_label.pack(side="left", padx=(0, 18))

        self.md_switch = ToggleSwitch(row4, "去除 Markdown 符号", self.clean_md_var,
                                      desc="** 加粗 **、# 标题等",
                                      command=self._on_option_changed)
        self.md_switch.pack(side="left")
        self.list_switch = ToggleSwitch(row4, "去除重复列表编号", self.fix_list_var,
                                      desc="适配自动编号的在线编辑器",
                                        command=self._on_option_changed)
        self.list_switch.pack(side="left", padx=(24, 0))
        self.blank_switch = ToggleSwitch(row4, "删除空白行", self.rm_blank_var,
                                         desc="段落之间不留空行",
                                         command=self._on_option_changed)
        self.blank_switch.pack(side="left", padx=(24, 0))

        self.btn_tidy = RoundButton(row4, "立即整理", self.clean_now, variant="soft",
                                    height=34, radius=10, font_spec=font(9), pad_x=14,
                                    width=110)
        self.btn_tidy.pack(side="right")
        self._cleanup_toggles = (self.md_switch, self.list_switch, self.blank_switch)

    # -- 操作按钮 ------------------------------------------------------- #
    def _build_actions(self, parent):
        bar = tk.Frame(parent, bg=C.BG)
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        self.btn_start = RoundButton(bar, "开始输入", self.start, variant="primary",
                                     glyph="▶", height=46, radius=14,
                                     font_spec=font(12, "bold"), pad_x=26, width=196)
        self.btn_start.pack(side="left")

        self.btn_restart = RoundButton(bar, "重新开始", self.restart, variant="secondary",
                                       glyph="↻", height=46, radius=14,
                                       font_spec=font(11, "bold"), pad_x=20, width=156)
        self.btn_restart.pack(side="left", padx=(10, 0))

        self.btn_stop = RoundButton(bar, "紧急停止", self.stop, variant="danger",
                                    glyph="■", height=46, radius=14,
                                    font_spec=font(11, "bold"), pad_x=20, width=156)
        self.btn_stop.pack(side="left", padx=(10, 0))
        self.btn_stop.set_state("disabled")

        self.shortcut_hint = tk.Label(bar, text="快捷键：F9 开始 / F8 重来 / Esc 停止 / Ctrl+Enter 开始",
                                      bg=C.BG, fg=C.MUTED, font=font(9))
        self.shortcut_hint.pack(side="right")
        self._actions_bar = bar

    # -- 进度区 --------------------------------------------------------- #
    def _build_progress(self, parent):
        card = RoundedBox(parent, radius=18, pad=13)
        card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._card_progress = card
        body = card.body
        body.columnconfigure(1, weight=1)

        self.ring = CountRing(body, size=46)
        self.ring.grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, 14))

        status_row = tk.Frame(body, bg=C.CARD)
        status_row.grid(row=0, column=1, sticky="ew")
        status_row.columnconfigure(0, weight=1)
        tk.Label(status_row, textvariable=self.status_var, bg=C.CARD, fg=C.TEXT,
                 font=font(11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(status_row, textvariable=self.percent_var, bg=C.CARD, fg=C.PRIMARY,
                 font=font(15, "bold", MONO)).grid(row=0, column=1, sticky="e")

        self.progress = SlimProgress(body, height=10)
        self.progress.grid(row=1, column=1, sticky="ew", pady=(8, 6))

        tk.Label(body, textvariable=self.eta_var, bg=C.CARD, fg=C.MUTED,
                 font=font(9)).grid(row=2, column=1, sticky="w")

    # -- 日志 ----------------------------------------------------------- #
    def _build_log(self, parent):
        card = RoundedBox(parent, radius=18, pad=12, shadow=False)
        card.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self._card_log = card
        body = card.body
        body.columnconfigure(0, weight=1)

        bar = tk.Frame(body, bg=C.CARD)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.log_header_btn = RoundButton(bar, "▸  运行日志", self._toggle_log,
                                          variant="ghost", height=30, radius=9,
                                          font_spec=font(9), pad_x=12, width=150)
        self.log_header_btn.grid(row=0, column=0, sticky="w")
        RoundButton(bar, "清空日志", self._clear_console, variant="quiet", height=30,
                    radius=9, font_spec=font(9), pad_x=12).grid(row=0, column=1, sticky="e")

        self.log_body = tk.Frame(body, bg=C.CARD, highlightthickness=0)
        self.log_body.columnconfigure(0, weight=1)
        self.log_body.rowconfigure(0, weight=1)

        self.log_panel = RoundedBox(self.log_body, radius=12, fill=C.CONSOLE_BG,
                                    border=C.CONSOLE_BG, pad=6, shadow=False,
                                    auto_height=False, height=105)
        self.log_panel.grid(row=0, column=0, sticky="nsew")
        self.log_panel.body.columnconfigure(0, weight=1)
        self.log_panel.body.rowconfigure(0, weight=1)

        self.console = tk.Text(self.log_panel.body, height=5, wrap="word", relief="flat",
                               bd=0, bg=C.CONSOLE_BG, fg=C.CONSOLE_FG,
                               insertbackground=C.CONSOLE_FG, font=font(9, family=MONO),
                               padx=12, pady=10, state="disabled", highlightthickness=0)
        self.console.grid(row=0, column=0, sticky="nsew")
        for tag, color in (("info", C.CONSOLE_FG), ("ok", C.CONSOLE_OK),
                           ("warn", C.CONSOLE_WARN), ("err", C.CONSOLE_ERR),
                           ("time", C.CONSOLE_MUTED)):
            self.console.tag_configure(tag, foreground=color)

    # ------------------------------------------------------------------ #
    # 交互回调
    # ------------------------------------------------------------------ #
    def _on_text_modified(self, _event=None):
        self.text_input.edit_modified(False)
        self._update_stats()

    # -- 右键菜单（复制 / 粘贴 / 剪切 / 全选）------------------------------ #
    def _build_context_menus(self):
        """给文本框和日志加右键菜单，方便复制粘贴。"""
        self._text_menu = tk.Menu(self.root, tearoff=0, font=font(9))
        self._text_menu.add_command(label="剪切", accelerator="Ctrl+X", command=self.cut_text)
        self._text_menu.add_command(label="复制", accelerator="Ctrl+C", command=self.copy_text)
        self._text_menu.add_command(label="粘贴", accelerator="Ctrl+V", command=self.paste_text)
        self._text_menu.add_separator()
        self._text_menu.add_command(label="全选", accelerator="Ctrl+A",
                                    command=lambda: self.text_input.tag_add("sel", "1.0", "end-1c"))
        self._text_menu.add_command(label="清空", command=self.clear_text)
        self.text_input.bind("<Button-3>", self._popup_text_menu)

    # 直接用剪贴板读写，避免依赖 Tk 的 <<Copy>>/<<Paste>> 虚拟事件
    def copy_text(self):
        try:
            data = self.text_input.get("sel.first", "sel.last")
        except tk.TclError:
            return
        if not data:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(data)
        self.log(f"已复制 {len(data)} 个字符到剪贴板。")

    def cut_text(self):
        try:
            data = self.text_input.get("sel.first", "sel.last")
        except tk.TclError:
            return
        if not data:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(data)
        self.text_input.delete("sel.first", "sel.last")
        self._update_stats()

    def paste_text(self):
        try:
            data = self.root.clipboard_get()
        except tk.TclError:
            return
        if not data:
            return
        try:
            self.text_input.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self.text_input.insert("insert", data)
        self.text_input.focus_set()
        self._update_stats()
        self.log(f"已粘贴 {len(data)} 个字符。")

        self._log_menu = tk.Menu(self.root, tearoff=0, font=font(9))
        self._log_menu.add_command(label="复制", command=self._copy_log_selection)
        self._log_menu.add_command(label="全选并复制", command=self._copy_all_log)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="清空日志", command=self._clear_console)
        self.console.bind("<Button-3>", self._popup_log_menu)

    def _popup_text_menu(self, event):
        self.text_input.focus_set()
        try:
            has_selection = bool(self.text_input.tag_ranges("sel"))
        except Exception:
            has_selection = False
        state = "normal" if has_selection else "disabled"
        try:
            self._text_menu.entryconfigure("剪切", state=state)
            self._text_menu.entryconfigure("复制", state=state)
            self._text_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._text_menu.grab_release()
        return "break"

    def _copy_log_selection(self):
        try:
            text = self.console.get("sel.first", "sel.last")
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _copy_all_log(self):
        text = self.console.get("1.0", "end-1c")
        if not text.strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _popup_log_menu(self, event):
        self.console.focus_set()
        try:
            self._log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._log_menu.grab_release()
        return "break"

    # -- 自适应布局：窄窗口切换紧凑模式 ---------------------------------- #
    def _on_root_configure(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        try:
            width = self.root.winfo_width()
        except Exception:
            return
        # 窗口尺寸变化后回到内容顶部，避免 Tk 为了显示焦点控件把内容顶偏
        try:
            self._scroll_canvas.yview_moveto(0)
        except Exception:
            pass
        self._apply_compact(width < px(880))

    def _on_scroll_set(self, first, last):
        """内容高于可视区域时才显示滚动条。"""
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._scrollbar.pack_forget()
        elif not self._scrollbar.winfo_ismapped():
            self._scrollbar.pack(side="right", fill="y")
        self._scrollbar.set(first, last)

    # -- 迷你模式：只留进度和按钮，窗口缩到最小 -------------------------- #
    def toggle_mini(self, preset=None):
        self._mini = (not getattr(self, "_mini", False)) if preset is None else bool(preset)
        self._apply_mini()
        self._save_settings()

    def _apply_mini(self):
        """迷你模式：隐藏文字框、设置和日志，只保留标题、按钮和进度。"""
        if self._mini:
            if not self._pre_mini_geometry:
                self._pre_mini_geometry = self.root.geometry()
            for widget in (self._card_editor, self._card_settings, self._card_log):
                widget.grid_remove()
            self._outer.rowconfigure(1, weight=0, minsize=0)
            self.shortcut_hint.pack_forget()
            # 迷你窗口很窄，标题行也要瘦身：只留程序名 + 展开/置顶
            self._version_label.pack_forget()
            self._author_label.pack_forget()
            self.subtitle_label.pack_forget()
            self._help_btn.pack_forget()
            self.mini_btn.set_text("展开")
            # 按钮收窄，保证在 470 逻辑像素宽里排得下
            self.btn_start.configure(width=px(132))
            self.btn_restart.configure(width=px(104))
            self.btn_stop.configure(width=px(104))
            self.btn_restart.set_text("重来")
            self.btn_stop.set_text("停止")
            w, h = int(400 * self.scale), int(260 * self.scale)
            vx, vy, vw, vh = virtual_screen_bounds()
            x = min(max(self.root.winfo_x(), vx if vw else 0), max(0, (vw or self.root.winfo_screenwidth()) - w))
            y = min(max(self.root.winfo_y(), vy if vh else 0), max(0, (vh or self.root.winfo_screenheight()) - h))
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        else:
            self._card_editor.grid()
            self._card_settings.grid()
            self._card_log.grid()
            self._outer.rowconfigure(1, weight=1, minsize=px(150))
            self.shortcut_hint.pack(side="right")
            self._version_label.pack(side="left", padx=(8, 0), pady=(6, 0))
            self._author_label.pack(side="left", padx=(6, 0), pady=(6, 0))
            self.subtitle_label.pack(anchor="w", pady=(3, 0))
            self._help_btn.pack(side="left", padx=(10, 0))
            self.mini_btn.set_text("迷你模式")
            self.btn_start.configure(width=px(196))
            self.btn_restart.configure(width=px(156))
            self.btn_stop.configure(width=px(156))
            self.btn_restart.set_text("重新开始")
            self.btn_stop.set_text("紧急停止")
            if self._pre_mini_geometry:
                self.root.geometry(self._pre_mini_geometry)
        self.root.after(60, self._on_root_configure)

    def _on_mousewheel(self, event):
        """滚轮滚动页面；鼠标停在文本框上时交给文本框自己处理。"""
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            widget = None
        if isinstance(widget, tk.Text):
            return
        bbox = self._scroll_canvas.bbox("all")
        if not bbox or bbox[3] <= self._scroll_canvas.winfo_height():
            return
        self._scroll_canvas.yview_scroll(int(-event.delta / 120) or 0, "units")

    def _apply_compact(self, compact: bool):
        """窄窗口时收起说明文字、缩短标签，保证各控件排得下。"""
        if getattr(self, "_compact", None) == compact:
            return
        self._compact = compact

        toggles = self._cleanup_toggles
        short_labels = ("去 Markdown", "去编号", "删空行")
        full_labels = ("去除 Markdown 符号", "去除重复列表编号", "删除空白行")
        for widget in toggles:
            widget.pack_forget()
            if widget.desc is not None:
                widget.desc.pack_forget()
        self._cleanup_label.pack_forget()
        self.btn_tidy.pack_forget()

        if compact:
            self._cleanup_label.configure(text="整理")
            self._cleanup_label.pack(side="left", padx=(0, 10))
            for idx, widget in enumerate(toggles):
                widget.label.configure(text=short_labels[idx])
                widget.pack(side="left", padx=((0 if idx == 0 else 10), 0))
            self.btn_tidy.pack(side="right")
            self.subtitle_label.configure(text="点进目标输入框 → F9 开始 · F8 重来 · Esc 停止")
            self.shortcut_hint.configure(text="F9 开始 · Esc 停止")
            self.delay_slider.configure(width=px(140))
            self.editor_hint.pack_forget()
            for btn in self._tool_buttons:
                btn.configure(width=px(58))
        else:
            self._cleanup_label.configure(text="文本整理")
            self._cleanup_label.pack(side="left", padx=(0, 18))
            for idx, widget in enumerate(toggles):
                widget.label.configure(text=full_labels[idx])
                if widget.desc is not None:
                    widget.desc.pack(anchor="w", pady=(px(1), 0))
                widget.pack(side="left", padx=((0 if idx == 0 else 24), 0))
            self.btn_tidy.pack(side="right")
            self.subtitle_label.configure(
                text="把光标点进目标输入框 → 按 F9 开始逐字输入   ·   F8 重新开始   ·   Esc 紧急停止")
            self.shortcut_hint.configure(text="快捷键：F9 开始 / F8 重来 / Esc 停止 / Ctrl+Enter 开始")
            self.delay_slider.configure(width=px(240))
            self.editor_hint.pack(side="left", padx=(8, 0))
            for btn in self._tool_buttons:
                btn.configure(width=getattr(btn, "_wide_width", px(70)))
        self._update_stats()

    def _on_ctrl_enter(self, _event=None):
        self.start()
        return "break"

    def _on_option_changed(self, *_):
        self._update_stats()
        self._save_settings()

    def _on_topmost_toggle(self):
        self._apply_topmost()
        self._save_settings()

    def _apply_topmost(self):
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    def _on_speed_preset(self, name: str):
        for label, value in self.SPEED_PRESETS:
            if label == name:
                self.delay_var.set(value)
                self.delay_slider._draw()
                self._on_delay_changed(value)
                return

    def _on_delay_changed(self, value: int):
        self.delay_label.configure(text=f"{value} 毫秒/字")
        self._sync_speed_preset()
        self._update_stats()
        self._save_settings()

    def _sync_speed_preset(self):
        value = self.delay_var.get()
        name = ""
        for label, preset in self.SPEED_PRESETS:
            if abs(preset - value) <= 2:
                name = label
                break
        self.speed_var.set(name)
        if hasattr(self, "speed_seg"):
            self.speed_seg._redraw()
        if hasattr(self, "delay_label"):
            self.delay_label.configure(text=f"{value} 毫秒/字")

    # -- 文本工具 ------------------------------------------------------- #
    def _preprocess(self, content: str) -> str:
        return preprocess_text(content,
                               markdown=bool(self.clean_md_var.get()),
                               blank_lines=bool(self.rm_blank_var.get()),
                               list_fix=bool(self.fix_list_var.get()))

    def _update_stats(self):
        content = self.text_input.get("1.0", "end-1c")
        cleaned = self._preprocess(content)
        total = effective_length(cleaned, self.newline_var.get())
        lines = len(content.split("\n")) if content else 0
        seconds = total * max(0, self.delay_var.get()) / 1000.0
        if self.newline_var.get() == "发送回车":
            seconds += max(0, lines - 1) * 0.05
        if getattr(self, "_compact", False):
            self.stats_left.configure(text=f"{len(content)} 字 · 预计 {seconds:.1f} 秒")
        else:
            self.stats_left.configure(
                text=f"共 {len(content)} 字 · {lines} 行 · 实际输入 {total} 个字符 · 预计 {seconds:.1f} 秒")
        self.stats_right.configure(text=f"换行：{self.newline_var.get()}")

    def import_text(self):
        path = filedialog.askopenfilename(
            title="导入文本", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        data = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, "r", encoding=encoding) as fh:
                    data = fh.read()
                break
            except UnicodeDecodeError:
                continue
        if data is None:
            self.log("导入失败：无法识别文件编码。", "err")
            return
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", data)
        self.log(f"已导入 {Path(path).name}（{len(data)} 字）。", "ok")
        self._update_stats()

    def export_text(self):
        content = self.text_input.get("1.0", "end-1c")
        if not content.strip():
            self.log("文本框是空的，没有可导出的内容。", "warn")
            return
        path = filedialog.asksaveasfilename(
            title="导出文本", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.log(f"已导出到 {Path(path).name}。", "ok")
        except Exception as exc:  # noqa: BLE001
            self.log(f"导出失败：{exc}", "err")

    def insert_sample(self):
        self.text_input.insert("insert", self.DEMO_TEXT)
        self._update_stats()

    def clear_text(self):
        if self.text_input.get("1.0", "end-1c").strip():
            if not messagebox.askyesno("清空文本", "确定要清空文本框中的内容吗？"):
                return
        self.text_input.delete("1.0", "end")
        self._update_stats()

    def clean_now(self):
        content = self.text_input.get("1.0", "end-1c")
        if not content.strip():
            self.log("文本框是空的，无需整理。", "warn")
            return
        cleaned = self._preprocess(content)
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", cleaned)
        self.log(f"已按当前选项整理文本（{len(content)} → {len(cleaned)} 字符）。", "ok")
        self._update_stats()

    def show_help(self):
        messagebox.showinfo(
            f"使用说明 · {APP_TITLE}",
            "1. 把要填的内容粘贴到文本框（可以带 Markdown 格式）。\n"
            "2. 用鼠标点一下目标网页的输入框，让光标停在里面。\n"
            "3. 回到本窗口点「开始输入」或直接按 F9，倒计时结束后就会逐字输入。\n\n"
            "F8：中断并从头重新输入\n"
            "Esc：紧急停止\n"
            "Ctrl+Enter：在文本框里直接开始\n\n"
            "提示：窗口可以置顶显示；输入速度、换行方式、文本整理选项都会被自动记住。\n\n"
            "──────────\n"
            f"{APP_TITLE}　作者：{APP_AUTHOR}\n"
            "本软件完全离线运行，不联网、不上传任何内容，也不收集使用数据。\n"
            "请勿用于考试、测验等需要本人独立完成的场景；使用本软件产生的后果由使用者自行承担。")

    # ------------------------------------------------------------------ #
    # 参数与流程
    # ------------------------------------------------------------------ #
    def _read_params(self, preset_text=None):
        content = preset_text if preset_text is not None else self.text_input.get("1.0", "end-1c")
        if not content.strip():
            self.log("请先在文本框里输入要录入的内容。", "warn")
            self.status_var.set("请先输入内容")
            self._flash_text_area()
            return None
        try:
            countdown = max(0, int(self.countdown_var.get()))
            delay_ms = max(0, int(self.delay_var.get()))
        except (tk.TclError, ValueError):
            self.log("倒计时和延迟请填写数字。", "warn")
            return None
        return content, countdown, delay_ms

    def _flash_text_area(self):
        wrap = self.text_wrap
        wrap.configure(highlightbackground=C.DANGER, highlightcolor=C.DANGER)
        self.root.after(900, lambda: wrap.configure(
            highlightbackground=C.BORDER, highlightcolor=C.PRIMARY))

    def start(self, preset_text=None):
        if self.worker and self.worker.is_alive():
            return
        params = self._read_params(preset_text)
        if not params:
            return
        content, countdown, delay_ms = params
        content = self._preprocess(content)
        self._launch(content, countdown, delay_ms,
                     self.newline_var.get(), bool(self.jitter_var.get()))

    def restart(self, preset_text=None):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.log("中断当前输入，将从头重新开始……", "warn")
            threading.Thread(target=self._restart_after_stop, daemon=True,
                             args=(preset_text,)).start()
            return
        self.start(preset_text)

    def _restart_after_stop(self, preset_text):
        if self.worker:
            self.worker.join(timeout=5)
        time.sleep(0.3)
        params = self._read_params(preset_text)
        if not params:
            return
        content, countdown, delay_ms = params
        content = self._preprocess(content)
        self._launch(content, countdown, delay_ms,
                     self.newline_var.get(), bool(self.jitter_var.get()))

    def stop(self):
        self.stop_event.set()
        self.log("收到停止指令，正在停止……", "warn")

    def _should_stop(self) -> bool:
        if self.stop_event.is_set() or key_down(VK_ESCAPE):
            self.stop_event.set()
            return True
        return False

    def _launch(self, content, countdown, delay_ms, newline_mode, jitter):
        self.stop_event.clear()
        self.ui_queue.put(("state", True))
        self.ui_queue.put(("reset",))
        self.worker = threading.Thread(
            target=self._type_worker, daemon=True,
            args=(content, countdown, delay_ms, newline_mode, jitter))
        self.worker.start()

    # -- 输入线程 ------------------------------------------------------- #
    def _type_worker(self, content, countdown, delay_ms, newline_mode, jitter):
        total = effective_length(content, newline_mode)
        base = delay_ms / 1000.0
        started = time.time()
        done = 0
        try:
            self.log(f"准备就绪，共 {total} 个字符。请确认光标已在目标输入框内。")
            for i in range(countdown, 0, -1):
                if self._should_stop():
                    self.log("已取消。", "warn")
                    self._finish(started, total, done, stopped=True)
                    return
                self.ui_queue.put(("countdown", i, countdown))
                self.log(f"  {i} …")
                time.sleep(1)
            if self._should_stop():
                self.log("已取消。", "warn")
                self._finish(started, total, done, stopped=True)
                return
            self.ui_queue.put(("countdown", 0, max(1, countdown)))
            self.log("开始输入（F8 重新开始，ESC 停止）……", "ok")
            self.ui_queue.put(("progress", 0, total))
            time.sleep(0.2)

            lines = content.split("\n")
            last_i = len(lines) - 1
            for li, raw_line in enumerate(lines):
                if self._should_stop():
                    self.log(f"已紧急停止，已完成 {done}/{total}。", "warn")
                    self._finish(started, total, done, stopped=True)
                    return
                line = raw_line.replace("\r", "")
                if line.startswith(EXIT_SENTINEL):
                    if newline_mode == "发送回车":
                        time.sleep(0.05)
                        send_vk(VK_RETURN)
                        time.sleep(0.1)
                    line = line[len(EXIT_SENTINEL):]

                for ch in line:
                    if self._should_stop():
                        self.log(f"已紧急停止，已完成 {done}/{total}。", "warn")
                        self._finish(started, total, done, stopped=True)
                        return
                    send_unicode(ch)
                    done += 1
                    self.ui_queue.put(("progress", done, total))
                    sleep_s = base
                    if jitter and base > 0:
                        sleep_s += random.uniform(-base * 0.3, base * 0.3)
                    time.sleep(max(0.0, sleep_s))

                if li < last_i:
                    if newline_mode == "转为空格":
                        send_unicode(" ")
                        done += 1
                    elif newline_mode == "发送回车":
                        send_vk(VK_RETURN)
                        done += 1
                        time.sleep(0.05)
                self.ui_queue.put(("progress", done, total))
                if done and done % 20 == 0:
                    self.log(f"  已输入 {done}/{total}")

            self.log("全部输入完成。", "ok")
            self._finish(started, total, done, stopped=False)
        except Exception as exc:  # noqa: BLE001
            self.log(f"发生错误：{exc}", "err")
            self._finish(started, total, done, stopped=True)
        finally:
            self.ui_queue.put(("state", False))

    def _finish(self, started, total, done, *, stopped):
        elapsed = max(0.001, time.time() - started)
        self.ui_queue.put(("done", done, total, elapsed, stopped))

    # ------------------------------------------------------------------ #
    # 主线程轮询
    # ------------------------------------------------------------------ #
    def log(self, text: str, level: str = "info"):
        self.ui_queue.put(("log", level, text))

    def _append_log(self, text: str, level: str = "info"):
        stamp = time.strftime("%H:%M:%S")
        self.console.configure(state="normal")
        self.console.insert("end", f"[{stamp}] ", "time")
        self.console.insert("end", text + "\n", level)
        self.console.configure(state="disabled")
        self.console.see("end")

    def _poll_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[2], msg[1])
                elif kind == "progress":
                    _, done, total = msg
                    frac = (done / total) if total else 0.0
                    self.progress.set(frac)
                    self.percent_var.set(f"{frac * 100:.0f}%")
                    self._update_eta(done, total)
                elif kind == "countdown":
                    _, value, total = msg
                    self.ring.set(value, total)
                    if value > 0:
                        self.status_var.set(f"{value} 秒后开始输入…")
                elif kind == "reset":
                    self.progress.reset()
                    self.percent_var.set("0%")
                    self.eta_var.set("等待开始")
                    self.ring.set(0, 1)
                    self.status_var.set("准备中…")
                elif kind == "state":
                    self._set_running(bool(msg[1]))
                elif kind == "done":
                    _, done, total, elapsed, stopped = msg
                    self._show_summary(done, total, elapsed, stopped)
        except queue.Empty:
            pass
        self.root.after(45, self._poll_queue)

    def _update_eta(self, done, total):
        if not self._started_at:
            self._started_at = time.time()
        remaining = max(0, total - done)
        if done <= 0:
            self.eta_var.set(f"共 {total} 个字符，即将开始…")
            return
        rate = done / max(0.001, time.time() - self._started_at)
        eta = remaining / max(0.01, rate)
        self.eta_var.set(f"已输入 {done} / {total} 字 · 约剩 {eta:.0f} 秒")

    def _show_summary(self, done, total, elapsed, stopped):
        self._started_at = 0.0
        if stopped:
            self.status_var.set(f"已停止 · 完成 {done}/{total}")
            self.eta_var.set(f"用时 {elapsed:.1f} 秒")
        else:
            self.status_var.set("全部输入完成")
            self.eta_var.set(f"共 {total} 个字符 · 用时 {elapsed:.1f} 秒")
            self.percent_var.set("100%")
            self.progress.set(1.0)
        self.ring.set(0, 1)

    def _set_running(self, running: bool):
        self._running = running
        self.btn_start.set_state("disabled" if running else "normal")
        self.btn_stop.set_state("normal" if running else "disabled")
        if not running and self.status_var.get() in ("准备中…",):
            self.status_var.set("就绪")

    def _toggle_log(self):
        self.log_expanded = not self.log_expanded
        self._resize_for_log()
        if self.log_expanded:
            self.log_body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
            self.log_header_btn.set_text("▾  运行日志")
        else:
            self.log_body.grid_forget()
            self.log_header_btn.set_text("▸  运行日志")
        self._save_settings()

    def _resize_for_log(self):
        """展开日志时尽量把窗口加高，避免把文本区压得太扁。"""
        try:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            limit = sh - px(70)
            if self.log_expanded:
                target = min(limit, h + px(130))
            else:
                target = max(px(640), h - px(130))
            if target != h:
                self.root.geometry(f"{w}x{target}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        except Exception:
            pass

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _poll_hotkeys(self):
        f8 = key_down(VK_F8)
        f9 = key_down(VK_F9)
        if f9 and not self.prev_f9:
            if self.worker and self.worker.is_alive():
                self.log("正在输入中，F9 已忽略；按 F8 可从头上重新输入。", "warn")
            else:
                self.start()
        if f8 and not self.prev_f8:
            self.restart()
        self.prev_f9, self.prev_f8 = f9, f8
        self.root.after(30, self._poll_hotkeys)

    # ------------------------------------------------------------------ #
    def _on_close(self):
        self.stop_event.set()
        self._write_settings()
        self.root.after(120, self.root.destroy)

    # ------------------------------------------------------------------ #
    # 自动化自检（仅通过 --selftest 触发，用于开发验证输入是否正确）
    # ------------------------------------------------------------------ #
    def run_selftest(self, target_pid: int, report_path: str):
        self._st_cases = [
            # (输入文本, 换行方式, 在记事本里期望看到的文本)
            ("1. 标题一\n2. 标题二\n正文段落", "发送回车",
             "1. 标题一\r\n标题二\r\n\r\n正文段落"),
            ("第一段\n第二段", "转为空格", "第一段 第二段"),
            ("第一段\n第二段", "跳过换行", "第一段第二段"),
            ("**加粗** 与 `代码` 和 ~~删除~~", "发送回车", "加粗 与 代码 和 删除"),
        ]
        self._st_index = -1
        self._st_target = target_pid
        self._st_report = report_path
        self._st_results = []
        self.root.after(900, self._st_next)

    def _st_trace(self, message: str):
        try:
            with open(self._st_report + ".trace", "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {message}\n")
        except Exception:
            pass

    def _st_focus_target(self):
        hwnd = find_window_for_pid(self._st_target)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return hwnd

    def _st_next(self):
        self._st_index += 1
        self._st_trace(f"next index={self._st_index}")
        if self._st_index >= len(self._st_cases):
            self._st_trace("writing report")
            with open(self._st_report, "w", encoding="utf-8") as fh:
                json.dump(self._st_results, fh, ensure_ascii=False, indent=2)
            self._st_trace("report written")
            self.root.after(150, self.root.destroy)
            return

        payload, mode, expected = self._st_cases[self._st_index]
        self.newline_var.set(mode)
        self.countdown_var.set(1)
        self.delay_var.set(0)
        self.jitter_var.set(False)
        self.clean_md_var.set(True)
        self.rm_blank_var.set(True)
        self.fix_list_var.set(True)
        self._st_expected = expected

        self._st_focus_target()
        self._st_trace("focus target requested")
        self.root.after(250, self._st_clear_and_type, payload)

    def _st_clear_and_type(self, payload):
        self._st_trace("clear and type")
        self._st_focus_target()
        send_ctrl_key(VK_A)
        time.sleep(0.05)
        send_vk(VK_DELETE)
        time.sleep(0.25)
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", payload)
        self.start()
        self._st_trace("worker started")
        self.root.after(200, self._st_wait)

    def _st_wait(self):
        if self.worker and self.worker.is_alive():
            self.root.after(150, self._st_wait)
            return
        self._st_trace("worker finished")
        self.root.after(450, self._st_collect)

    def _st_collect(self):
        self._st_trace("collect")
        self._st_focus_target()
        time.sleep(0.15)
        send_ctrl_key(VK_A)
        time.sleep(0.1)
        send_ctrl_key(VK_C)
        time.sleep(0.25)
        actual = clipboard_text()
        # Tk 文本框全选复制时会带上末尾换行，这里忽略它
        actual = actual.rstrip("\r\n")
        self._st_trace(f"clipboard={actual!r}")
        payload, mode, expected = self._st_cases[self._st_index]
        self._st_results.append({
            "payload": payload,
            "newline_mode": mode,
            "expected": expected,
            "actual": actual,
            "ok": actual == expected,
        })
        self.root.after(400, self._st_next)


def main():
    global SCALE
    SCALE = enable_dpi_awareness()
    scale = SCALE
    root = tk.Tk()
    set_app_icon(root)
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Slim.Vertical.TScrollbar", gripcount=0,
                        background=C.BORDER_STRONG, darkcolor=C.CARD,
                        lightcolor=C.CARD, troughcolor=C.CARD_SOFT,
                        bordercolor=C.CARD, arrowcolor=C.MUTED, arrowsize=12, width=10)
        style.map("Slim.Vertical.TScrollbar", background=[("active", C.MUTED)])
    except Exception:
        pass
    app = AutoTypeApp(root, scale)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    if "--selftest" in sys.argv:
        target = int(sys.argv[sys.argv.index("--target-pid") + 1])
        report = sys.argv[sys.argv.index("--report") + 1]
        app.countdown_var.set(1)
        app.run_selftest(target, report)
    elif "--demo" in sys.argv:
        app.text_input.insert("1.0", AutoTypeApp.DEMO_TEXT)
        app.log("这是演示文本，用于预览界面效果。")
        app.log("把光标点进目标输入框后按 F9 即可开始。", "ok")
        app.log("提示：输入速度可以在下方随时调整。", "warn")
    root.mainloop()


if __name__ == "__main__":
    main()
