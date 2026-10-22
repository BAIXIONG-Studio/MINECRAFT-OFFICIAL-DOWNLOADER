#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 原版官方文件下载工具（GUI 版）
============================================
功能：
  1. 从 Mojang 官方版本清单（version_manifest_v2.json）获取全部版本元数据；
  2. 手动选择游戏目录（.minecraft 文件夹），按官方目录结构安装；
  3. 下载客户端 JAR，校验 SHA-1 与文件大小，全部通过后才安装到正确版本目录；
  4. 下载/校验失败时保护已有文件：先写临时文件，校验成功后才原子替换；
  5. 可选同时写入 version JSON（PCL 启动该版本必需）；
  6. 可选 HTTP(S) 代理（国内用户可配合代理访问 Mojang）。

兼容性：Plain Craft Launcher（PCL2）等启动器使用的官方目录结构：
        <游戏目录>/versions/<版本ID>/<版本ID>.jar
        <游戏目录>/versions/<版本ID>/<版本ID>.json

运行环境：Python 3.8+（仅标准库，无第三方运行依赖）
构建 EXE：见 build.bat / build_github_actions.yml（PyInstaller --onefile --windowed）
"""

import hashlib
import json
import os
import queue
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    HAS_TK = True
except Exception:  # 无图形环境时允许命令行/逻辑测试
    HAS_TK = False

APP_NAME = "Minecraft 原版官方文件下载工具"
APP_VERSION = "1.0.0"
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
USER_AGENT = "MCOfficialDownloader/%s (Minecraft official file helper)" % APP_VERSION
DEFAULT_TIMEOUT = 30          # 元数据请求超时（秒）
DOWNLOAD_TIMEOUT = 60         # 下载读超时（秒）
CHUNK_SIZE = 64 * 1024        # 64KB 分块读写
RETRY_TIMES = 3               # 下载重试次数
CACHE_FILE_NAME = "manifest_cache.json"
CONFIG_FILE_NAME = "mc_downloader_config.json"

TYPE_NAMES = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧版 Beta",
    "old_alpha": "旧版 Alpha",
}
TYPE_ORDER = ["release", "snapshot", "old_beta", "old_alpha"]


# ---------------------------------------------------------------------------
# 基础工具：路径 / 配置
# ---------------------------------------------------------------------------

def app_base_dir():
    """程序所在目录（打包后为 EXE 所在目录，便于便携式运行）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_file_path():
    """配置文件路径：优先程序目录（便携），不可写时退回用户主目录。"""
    base = app_base_dir()
    path = os.path.join(base, CONFIG_FILE_NAME)
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except OSError:
        fallback_dir = os.path.join(os.path.expanduser("~"), ".mc_official_downloader")
        os.makedirs(fallback_dir, exist_ok=True)
        return os.path.join(fallback_dir, CONFIG_FILE_NAME)


def load_config():
    try:
        with open(config_file_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(config_file_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def cache_file_path():
    return os.path.join(config_file_path().rsplit(os.sep, 1)[0], CACHE_FILE_NAME)


def load_manifest_cache():
    try:
        with open(cache_file_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "versions" in data:
            return data
    except Exception:
        pass
    return None


def save_manifest_cache(manifest):
    try:
        with open(cache_file_path(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 网络层
# ---------------------------------------------------------------------------

class NetError(Exception):
    """网络/校验相关错误，携带用户可读信息。"""


def build_opener(proxy):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return urllib.request.build_opener(*handlers)


def http_request(opener, url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, */*",
        },
    )
    return opener.open(req, timeout=timeout)


def fetch_json(opener, url, timeout=DEFAULT_TIMEOUT):
    """获取并解析 JSON。"""
    try:
        with http_request(opener, url, timeout) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise NetError("HTTP %s：%s" % (e.code, url)) from e
    except urllib.error.URLError as e:
        raise NetError("网络错误：%s（%s）" % (e.reason, url)) from e
    except Exception as e:
        raise NetError("数据解析失败：%s" % e) from e


def fetch_version_raw(opener, url, expected_sha1=None, timeout=DEFAULT_TIMEOUT):
    """获取版本 JSON 原始字节并校验 SHA-1（与官方清单一致），返回 (bytes, dict)。"""
    try:
        with http_request(opener, url, timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise NetError("HTTP %s：%s" % (e.code, url)) from e
    except urllib.error.URLError as e:
        raise NetError("网络错误：%s（%s）" % (e.reason, url)) from e

    if expected_sha1:
        got = hashlib.sha1(raw).hexdigest()
        if got.lower() != expected_sha1.lower():
            raise NetError(
                "版本 JSON SHA-1 校验失败：实际 %s，应为 %s" % (got, expected_sha1)
            )
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise NetError("版本 JSON 解析失败：%s" % e) from e
    return raw, obj


def download_to_file(opener, url, dest, expected_size, progress_cb=None, cancel_evt=None):
    """
    流式下载到 dest（临时文件）。
    返回 (实际字节数, SHA-1 十六进制)。失败抛出 NetError；取消时抛出 NetError("已取消")。
    """
    sha = hashlib.sha1()
    total = expected_size if expected_size else 0
    done = 0
    last_err = None

    for attempt in range(1, RETRY_TIMES + 1):
        try:
            with http_request(opener, url, DOWNLOAD_TIMEOUT) as resp:
                length_header = resp.headers.get("Content-Length")
                if total == 0 and length_header:
                    try:
                        total = int(length_header)
                    except ValueError:
                        pass
                with open(dest, "wb") as f:
                    while True:
                        if cancel_evt is not None and cancel_evt.is_set():
                            raise NetError("已取消")
                        block = resp.read(CHUNK_SIZE)
                        if not block:
                            break
                        f.write(block)
                        sha.update(block)
                        done += len(block)
                        if progress_cb is not None:
                            progress_cb(done, total)
            return done, sha.hexdigest()
        except NetError:
            raise
        except Exception as e:
            last_err = e
            if attempt < RETRY_TIMES and not (cancel_evt is not None and cancel_evt.is_set()):
                time.sleep(1.0 * attempt)
                continue
    raise NetError("下载失败（已重试 %d 次）：%s" % (RETRY_TIMES, last_err))


# ---------------------------------------------------------------------------
# 校验与安装
# ---------------------------------------------------------------------------

def sha1_of_file(path):
    sha = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            sha.update(block)
    return sha.hexdigest()


def file_matches(path, sha1_hex, size):
    """判断已有文件是否已是指定内容（大小 + SHA-1 双校验）。"""
    if not os.path.isfile(path):
        return False
    try:
        if size is not None and os.path.getsize(path) != size:
            return False
        if sha1_hex and sha1_of_file(path).lower() != sha1_hex.lower():
            return False
    except OSError:
        return False
    return True


def remove_quiet(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def install_client_jar(opener, game_dir, version_id, client_info,
                       progress_cb=None, log_cb=None, cancel_evt=None):
    """
    下载并校验安装客户端 JAR。失败时保证目标位置已有文件不被破坏。
    返回 True（成功安装或已存在且有效）。
    """
    versions_dir = os.path.join(game_dir, "versions")
    vdir = os.path.join(versions_dir, version_id)
    os.makedirs(vdir, exist_ok=True)
    jar_path = os.path.join(vdir, version_id + ".jar")

    expected_size = client_info.get("size")
    expected_sha1 = client_info.get("sha1")
    url = client_info.get("url")

    if not url:
        raise NetError("该版本元数据中不包含客户端 JAR 下载地址，跳过。")

    # 1) 目标已存在且校验通过 → 直接跳过（保护已有文件 + 省流量）
    if file_matches(jar_path, expected_sha1, expected_size):
        log_cb("[%s] 客户端 JAR 已存在且 SHA-1/大小校验通过，无需下载。" % version_id)
        return True

    tmp = jar_path + ".part"
    remove_quiet(tmp)
    try:
        log_cb("[%s] 开始下载客户端 JAR（%.1f MB）..." % (
            version_id, (expected_size or 0) / 1024.0 / 1024.0))
        size, sha1_hex = download_to_file(
            opener, url, tmp, expected_size, progress_cb, cancel_evt)
    except NetError as e:
        remove_quiet(tmp)  # 清理临时文件，目标文件不受影响
        raise NetError("[%s] 下载失败：%s" % (version_id, e))

    # 2) 双校验：文件大小 + SHA-1
    if expected_size is not None and size != expected_size:
        remove_quiet(tmp)
        raise NetError(
            "[%s] 文件大小校验失败：实际 %d 字节，应为 %d 字节。已保留原有文件。" %
            (version_id, size, expected_size))
    if expected_sha1 and sha1_hex.lower() != expected_sha1.lower():
        remove_quiet(tmp)
        raise NetError(
            "[%s] SHA-1 校验失败：实际 %s，应为 %s。已保留原有文件。" %
            (version_id, sha1_hex, expected_sha1))

    log_cb("[%s] SHA-1 与文件大小校验通过（%s）。" % (version_id, sha1_hex))

    # 3) 原子替换：此时才触碰目标文件；替换失败则保留旧文件
    try:
        os.replace(tmp, jar_path)
    except OSError as e:
        remove_quiet(tmp)
        raise NetError(
            "[%s] 写入目标失败（可能被启动器/游戏占用）：%s。已保留原有文件。" %
            (version_id, e))
    log_cb("[%s] 已安装：%s" % (version_id, jar_path))
    return True


def install_version_json(opener, game_dir, version_id, version_url, expected_sha1,
                         log_cb=None):
    """下载版本 JSON 原始字节并校验 SHA-1 后写入（PCL 启动该版本必需）。"""
    versions_dir = os.path.join(game_dir, "versions")
    vdir = os.path.join(versions_dir, version_id)
    os.makedirs(vdir, exist_ok=True)
    json_path = os.path.join(vdir, version_id + ".json")

    if file_matches(json_path, expected_sha1, None):
        log_cb("[%s] 版本 JSON 已存在且校验通过，无需下载。" % version_id)
        return

    raw, _obj = fetch_version_raw(opener, version_url, expected_sha1)
    tmp = json_path + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        os.replace(tmp, json_path)
    except OSError as e:
        remove_quiet(tmp)
        raise NetError("[%s] 版本 JSON 写入失败：%s" % (version_id, e))
    log_cb("[%s] 版本 JSON 已写入（SHA-1 校验通过）。" % version_id)


def scan_installed_versions(game_dir):
    """扫描游戏目录 versions 下已安装版本，返回 [(id, 状态)]。只做轻量检查。"""
    versions_dir = os.path.join(game_dir, "versions")
    result = []
    if not os.path.isdir(versions_dir):
        return result
    for name in sorted(os.listdir(versions_dir), key=str.lower):
        d = os.path.join(versions_dir, name)
        if not os.path.isdir(d):
            continue
        jar = os.path.join(d, name + ".jar")
        jsn = os.path.join(d, name + ".json")
        if os.path.isfile(jar):
            if os.path.isfile(jsn):
                result.append((name, "正常"))
            else:
                result.append((name, "缺 JSON"))
        else:
            if os.path.isfile(jsn):
                result.append((name, "缺 JAR"))
            else:
                result.append((name, "目录为空"))
    return result


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("%s v%s" % (APP_NAME, APP_VERSION))
        self.root.geometry("900x680")
        self.root.minsize(780, 580)

        self.ui_queue = queue.Queue()
        self.cancel_evt = threading.Event()
        self.busy = False

        self.manifest = None            # 完整清单 dict
        self.versions_all = []          # 全部版本条目
        self.versions_shown = []        # 当前过滤后显示的条目（与 Listbox 顺序一致）
        self.filter_vars = {}

        self._build_ui()
        self._load_config_to_ui()
        self._poll_queue()

        # 应用图标（EXE 同目录存在 icon.ico 时使用）
        icon = os.path.join(app_base_dir(), "assets", "BX Studio.ico")
        if not os.path.isfile(icon):
            icon = os.path.join(app_base_dir(), "icon.ico")
        if os.path.isfile(icon):
            try:
                root.iconbitmap(icon)
            except Exception:
                pass

        # 启动后自动在后台刷新官方版本清单
        self.root.after(300, self.start_refresh)

    # ---------------- UI 构建 ----------------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 1) 游戏目录
        frm_dir = ttk.LabelFrame(self.root, text=" 游戏目录 ")
        frm_dir.pack(fill="x", **pad)
        row = ttk.Frame(frm_dir)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="游戏目录（.minecraft 文件夹）：").pack(side="left")
        self.var_dir = tk.StringVar()
        ent_dir = ttk.Entry(row, textvariable=self.var_dir)
        ent_dir.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=self.choose_dir).pack(side="left")

        # 2) 版本清单 + 快捷下载
        frm_manifest = ttk.LabelFrame(self.root, text=" 官方版本清单 ")
        frm_manifest.pack(fill="x", **pad)
        row = ttk.Frame(frm_manifest)
        row.pack(fill="x", padx=6, pady=2)
        self.var_manifest = tk.StringVar(value="版本清单：未加载")
        ttk.Label(row, textvariable=self.var_manifest).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="刷新清单", command=self.start_refresh).pack(side="left", padx=2)
        ttk.Button(row, text="下载最新正式版", command=lambda: self.quick_download("release")).pack(side="left", padx=2)
        ttk.Button(row, text="下载最新快照", command=lambda: self.quick_download("snapshot")).pack(side="left", padx=2)
        ttk.Button(row, text="扫描已安装版本", command=self.scan_installed).pack(side="left", padx=2)

        # 3) 过滤
        frm_filter = ttk.Frame(frm_manifest)
        frm_filter.pack(fill="x", padx=6, pady=2)
        ttk.Label(frm_filter, text="显示：").pack(side="left")
        for key in TYPE_ORDER:
            var = tk.BooleanVar(value=(key in ("release", "snapshot")))
            self.filter_vars[key] = var
            cb = ttk.Checkbutton(frm_filter, text=TYPE_NAMES[key], variable=var,
                                 command=self.rebuild_list)
            cb.pack(side="left", padx=4)

        # 4) 版本列表
        frm_list = ttk.Frame(self.root)
        frm_list.pack(fill="both", expand=True, **pad)
        self.lb = tk.Listbox(frm_list, font=("Consolas", 10), selectmode="single",
                             activestyle="dotbox")
        sb = ttk.Scrollbar(frm_list, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", self.on_select)
        self.lb.bind("<Double-Button-1>", lambda e: self.start_download())

        # 5) 操作区
        frm_ops = ttk.Frame(self.root)
        frm_ops.pack(fill="x", **pad)
        self.var_write_json = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm_ops, text="同时写入 version JSON（PCL 启动该版本必需）",
                        variable=self.var_write_json).pack(side="left")
        ttk.Label(frm_ops, text="代理(可选)：").pack(side="left", padx=(12, 0))
        self.var_proxy = tk.StringVar()
        ttk.Entry(frm_ops, textvariable=self.var_proxy, width=28).pack(side="left", padx=4)
        self.btn_download = ttk.Button(frm_ops, text="下载选中版本", command=self.start_download)
        self.btn_download.pack(side="right", padx=4)
        self.btn_cancel = ttk.Button(frm_ops, text="取消", command=self.cancel_download,
                                     state="disabled")
        self.btn_cancel.pack(side="right", padx=4)
        self.btn_open_dir = ttk.Button(frm_ops, text="打开版本目录", command=self.open_version_dir)
        self.btn_open_dir.pack(side="right", padx=4)

        # 6) 进度
        frm_prog = ttk.Frame(self.root)
        frm_prog.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=1.0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(frm_prog, textvariable=self.var_status, width=24,
                  anchor="e").pack(side="left", padx=8)

        # 7) 日志
        frm_log = ttk.LabelFrame(self.root, text=" 日志 ")
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(frm_log, height=12, state="disabled",
                                                 font=("Consolas", 9), wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=4, pady=4)
        self.txt_log.tag_configure("ok", foreground="#1e7e34")
        self.txt_log.tag_configure("warn", foreground="#b26a00")
        self.txt_log.tag_configure("err", foreground="#c62828")
        self.txt_log.tag_configure("info", foreground="#444444")

        # 8) 状态栏
        self.var_sb = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.var_sb, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

    # ---------------- 配置 ----------------

    def _load_config_to_ui(self):
        cfg = load_config()
        if cfg.get("game_dir"):
            self.var_dir.set(cfg["game_dir"])
        if cfg.get("proxy"):
            self.var_proxy.set(cfg["proxy"])

    def _save_current_config(self):
        cfg = load_config()
        cfg["game_dir"] = self.var_dir.get().strip()
        cfg["proxy"] = self.var_proxy.get().strip()
        save_config(cfg)

    # ---------------- 队列轮询（UI 线程更新） ----------------

    def _post(self, kind, *args):
        self.ui_queue.put((kind, args))

    def _poll_queue(self):
        try:
            while True:
                kind, args = self.ui_queue.get_nowait()
                handler = getattr(self, "_on_" + kind, None)
                if handler:
                    handler(*args)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    # ---------------- 日志与状态 ----------------

    def _log(self, msg, level="info"):
        self._post("log", msg, level)

    def _on_log(self, msg, level):
        self.txt_log.configure(state="normal")
        stamp = time.strftime("%H:%M:%S")
        self.txt_log.insert("end", "[%s] %s\n" % (stamp, msg), level)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_status(self, text):
        self._post("status", text)

    def _on_status(self, text):
        self.var_status.set(text)
        self.var_sb.set(text)

    def _set_progress(self, frac):
        self._post("progress", frac)

    def _on_progress(self, frac):
        if frac is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=max(0.0, min(1.0, frac)))

    def _set_busy(self, busy):
        self._post("busy", busy)

    def _on_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_download.configure(state=state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    # ---------------- 操作：目录 ----------------

    def choose_dir(self):
        if self.busy:
            return
        initial = self.var_dir.get().strip() or os.path.expanduser("~")
        chosen = filedialog.askdirectory(title="选择游戏目录（.minecraft 文件夹）", initialdir=initial)
        if chosen:
            self.var_dir.set(chosen)
            self._save_current_config()

    def open_version_dir(self):
        game_dir = self.var_dir.get().strip()
        if not game_dir:
            messagebox.showwarning(APP_NAME, "请先选择游戏目录。")
            return
        target = os.path.join(game_dir, "versions")
        os.makedirs(target, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system('open "%s"' % target)
            else:
                os.system('xdg-open "%s" >/dev/null 2>&1 &' % target)
        except Exception as e:
            self._log("无法打开目录：%s" % e, "err")

    # ---------------- 操作：清单 ----------------

    def start_refresh(self):
        if self.busy:
            return
        # 先展示缓存，后台拉取最新
        cached = load_manifest_cache()
        if cached:
            self._apply_manifest(cached, from_cache=True)
        self._set_busy(True)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            proxy = self.var_proxy.get().strip() or None
            opener = build_opener(proxy)
            manifest = fetch_json(opener, MANIFEST_URL)
            save_manifest_cache(manifest)
            self._post("manifest", manifest, False)
        except NetError as e:
            self._log("刷新官方版本清单失败：%s" % e, "err")
            if not load_manifest_cache():
                self._log("且本地无清单缓存，请检查网络后点击“刷新清单”。", "err")
            self._post("status", "清单刷新失败")
        finally:
            self._set_busy(False)

    def _on_manifest(self, manifest, from_cache):
        self.manifest = manifest
        self.versions_all = list(manifest.get("versions", []))
        latest = manifest.get("latest", {})
        rel = latest.get("release", "?")
        snp = latest.get("snapshot", "?")
        n = len(self.versions_all)
        self.var_manifest.set(
            "共 %d 个版本 ｜ 最新正式版 %s ｜ 最新快照 %s%s" %
            (n, rel, snp, "（缓存）" if from_cache else "（官方源）"))
        self.rebuild_list()
        self._set_status("版本清单已加载：%d 个版本" % n)

    def rebuild_list(self):
        if not self.versions_all:
            return
        sel = self.lb.curselection()
        keep_id = None
        if sel:
            idx = sel[0]
            if 0 <= idx < len(self.versions_shown):
                keep_id = self.versions_shown[idx]["id"]
        shown = []
        for v in self.versions_all:
            if self.filter_vars.get(v.get("type"), tk.BooleanVar()).get():
                shown.append(v)
        self.versions_shown = shown
        self.lb.delete(0, "end")
        for v in shown:
            self.lb.insert("end", "%-22s [%s]" % (v["id"], TYPE_NAMES.get(v.get("type"), v.get("type", "?"))))
        if keep_id:
            for i, v in enumerate(shown):
                if v["id"] == keep_id:
                    self.lb.selection_set(i)
                    self.lb.see(i)
                    break

    # ---------------- 操作：选择 / 快捷下载 ----------------

    def on_select(self, _event=None):
        pass  # 选中即用，无需额外逻辑

    def quick_download(self, vtype):
        if not self.manifest or self.busy:
            if self.busy:
                self._log("当前有任务进行中，请稍候。", "warn")
            return
        vid = (self.manifest.get("latest") or {}).get(vtype)
        if not vid:
            self._log("清单中未找到最新%s。请先刷新清单。" % TYPE_NAMES.get(vtype, vtype), "warn")
            return
        for i, v in enumerate(self.versions_shown):
            if v["id"] == vid:
                self.lb.selection_clear(0, "end")
                self.lb.selection_set(i)
                self.lb.see(i)
                self.start_download()
                return
        # 未在过滤列表 → 临时加入
        for v in self.versions_all:
            if v["id"] == vid:
                self._log("“%s”未在当前过滤中，已自动下载。" % vid, "info")
                self._download_version(v)
                return
        self._log("清单中未找到版本 %s。" % vid, "warn")

    # ---------------- 操作：下载安装 ----------------

    def start_download(self):
        if self.busy:
            self._log("当前有任务进行中，请稍候。", "warn")
            return
        sel = self.lb.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "请先在列表中选择一个版本。\n\n也可直接点击“下载最新正式版 / 下载最新快照”。")
            return
        idx = sel[0]
        if not (0 <= idx < len(self.versions_shown)):
            return
        self._download_version(self.versions_shown[idx])

    def _download_version(self, version):
        game_dir = self.var_dir.get().strip()
        if not game_dir:
            messagebox.showwarning(APP_NAME, "请先选择游戏目录（.minecraft 文件夹）。")
            return
        if not os.path.isdir(game_dir):
            messagebox.showwarning(APP_NAME, "所选目录不存在或不是文件夹：\n%s" % game_dir)
            return
        proxy = self.var_proxy.get().strip() or None
        self._save_current_config()
        self.cancel_evt.clear()
        self._set_busy(True)
        self._set_progress(None)
        self._log("======== 开始处理版本 %s ========" % version["id"], "info")
        threading.Thread(target=self._download_worker,
                         args=(version, game_dir, proxy), daemon=True).start()

    def _download_worker(self, version, game_dir, proxy):
        vid = version["id"]
        ok = False
        try:
            opener = build_opener(proxy)
            # 1) 获取版本元数据（含客户端 JAR 的 url / sha1 / size）
            self._log("[%s] 获取版本元数据…" % vid, "info")
            raw_json, vjson = fetch_version_raw(
                opener, version["url"], version.get("sha1"))
            client_info = ((vjson.get("downloads") or {}).get("client")) or {}
            if not client_info.get("url"):
                raise NetError("[%s] 该版本元数据中缺少客户端 JAR 下载信息。" % vid)

            # 2) 下载 + 校验 + 安装 JAR
            def prog(done, total):
                if total:
                    self._set_progress(done / float(total))
                else:
                    self._set_progress(None)
            install_client_jar(opener, game_dir, vid, client_info,
                               progress_cb=prog, log_cb=self._log,
                               cancel_evt=self.cancel_evt)

            # 3) 可选：写入版本 JSON（PCL 启动必需）
            if self.var_write_json.get():
                install_version_json(opener, game_dir, vid, version["url"],
                                     version.get("sha1"), log_cb=self._log)
            else:
                self._log("[%s] 已跳过写入版本 JSON。" % vid, "warn")

            self._log("[%s] 安装完成。" % vid, "ok")
            ok = True
        except NetError as e:
            self._log(str(e), "err")
        except Exception as e:
            self._log("发生未预期错误：%s" % e, "err")
        finally:
            self._set_progress(1.0 if ok else None)
            self._set_busy(False)
            self._post("done", ok, vid)

    def cancel_download(self):
        if self.busy:
            self.cancel_evt.set()
            self._log("正在取消…", "warn")
            self.btn_cancel.configure(state="disabled")

    # ---------------- 操作：扫描已安装 ----------------

    def scan_installed(self):
        if self.busy:
            return
        game_dir = self.var_dir.get().strip()
        if not game_dir:
            messagebox.showwarning(APP_NAME, "请先选择游戏目录（.minecraft 文件夹）。")
            return
        if not os.path.isdir(game_dir):
            messagebox.showwarning(APP_NAME, "所选目录不存在或不是文件夹：\n%s" % game_dir)
            return
        versions_dir = os.path.join(game_dir, "versions")
        if not os.path.isdir(versions_dir):
            self._log("目录中没有 versions 文件夹（尚未安装任何版本）。", "warn")
            return
        result = scan_installed_versions(game_dir)
        if not result:
            self._log("versions 文件夹存在，但没有发现版本目录。", "warn")
            return
        ok_n = sum(1 for _, s in result if s == "正常")
        self._log("==== 已安装版本扫描（共 %d 个，正常 %d 个）====" % (len(result), ok_n), "info")
        for vid, status in result:
            level = "ok" if status == "正常" else "warn"
            self._log("  %-24s %s" % (vid, status), level)
        self._log("提示：状态为“缺 JAR/缺 JSON”的版本，可在上方官方清单中选择对应版本重新下载。", "info")

    # ---------------- 收尾 ----------------

    def _on_done(self, ok, vid):
        if ok:
            self._set_status("完成：%s 已安装" % vid)
            messagebox.showinfo(APP_NAME,
                "版本 %s 安装完成。\n\n文件位置：\n<游戏目录>/versions/%s/%s.jar\n\n"
                "在 PCL 中刷新/重启后即可看到该版本。" % (vid, vid, vid))
        else:
            self._set_status("失败：%s（详见日志）" % vid)

    def run(self):
        self.root.mainloop()


def main():
    if not HAS_TK:
        print("%s 需要图形界面环境（tkinter），无法启动。" % APP_NAME, file=sys.stderr)
        return 1
    # Windows 高 DPI 适配（清晰文字）
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass
    # Linux/X11：初始化 X 线程支持，避免后台线程与 Tk 交互时崩溃（Windows 不受影响）
    elif sys.platform.startswith("linux"):
        try:
            import ctypes
            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            x11.XInitThreads(0)
        except Exception:
            pass
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BXStudio.MCOfficialDownloader.1")
    except Exception:
        pass
    
    root = tk.Tk()
    App(root).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
