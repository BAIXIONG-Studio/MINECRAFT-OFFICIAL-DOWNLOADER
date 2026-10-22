#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 原版官方文件下载工具 · PySide6 界面层
================================================
复用 BAIXIONG Studio「黑金」主题（theme.py）与侧边栏 + 页面堆栈结构（参考 main_ui.py）。

逻辑层见 mc_core.py（下载 / SHA-1+大小双校验 / 失败保护安装 / 清单缓存）。
"""

import ctypes
import html
import os
import sys
import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import mc_core
from theme import apply_dark_theme


def base_dir():
    """打包后返回 EXE 解压目录（_MEIPASS），开发时返回脚本所在目录。"""
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


def icon_path():
    """查找应用图标：优先 assets/BX Studio.ico，其次根目录 icon.ico。"""
    for p in (os.path.join(base_dir(), "assets", "BX MCOD.ico"),
              os.path.join(base_dir(), "icon.ico")):
        if os.path.isfile(p):
            return p
    return None


# ============================================================
# 后台下载线程
# Qt 规则：子线程不能碰控件，所有回传都走信号
# ============================================================
class DownloadWorker(QThread):
    log_signal = Signal(str, str)       # (级别, 消息)  级别: info/ok/warn/err
    progress_signal = Signal(float)     # 0.0 ~ 1.0
    done_signal = Signal(bool, str)     # (是否成功, 版本ID)

    def __init__(self, version, game_dir, proxy, write_json, cancel_evt, parent=None):
        super().__init__(parent)
        self.version = version
        self.game_dir = game_dir
        self.proxy = proxy
        self.write_json = write_json
        self.cancel_evt = cancel_evt

    def run(self):
        vid = self.version["id"]
        ok = False
        try:
            opener = mc_core.build_opener(self.proxy)
            self.log_signal.emit("info", "[%s] 获取版本元数据…" % vid)
            _raw, vjson = mc_core.fetch_version_raw(
                opener, self.version["url"], self.version.get("sha1"))
            client_info = ((vjson.get("downloads") or {}).get("client")) or {}
            if not client_info.get("url"):
                raise mc_core.NetError("[%s] 该版本元数据中缺少客户端 JAR 下载信息。" % vid)

            def prog(done, total):
                if total:
                    self.progress_signal.emit(done / float(total))

            mc_core.install_client_jar(
                opener, self.game_dir, vid, client_info,
                progress_cb=prog,
                log_cb=lambda m: self.log_signal.emit("info", m),
                cancel_evt=self.cancel_evt)

            if self.write_json:
                mc_core.install_version_json(
                    opener, self.game_dir, vid, self.version["url"],
                    self.version.get("sha1"),
                    log_cb=lambda m: self.log_signal.emit("info", m))
            else:
                self.log_signal.emit("warn", "[%s] 已跳过写入版本 JSON。" % vid)

            self.log_signal.emit("ok", "[%s] 安装完成。" % vid)
            ok = True
        except mc_core.NetError as e:
            self.log_signal.emit("err", str(e))
        except Exception as e:
            self.log_signal.emit("err", "发生未预期错误：%s" % e)
        finally:
            self.progress_signal.emit(1.0 if ok else 0.0)
            self.done_signal.emit(ok, vid)


# ============================================================
# 页面一：下载页
# ============================================================
class DownloadPage(QWidget):
    manifest_loaded = Signal(dict)      # 清单 dict（含 versions / latest）
    thread_log = Signal(str, str)       # 后台线程发日志专用（跨线程安全）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manifest = None
        self.versions_all = []
        self.versions_shown = []
        self.worker = None
        self.cancel_evt = threading.Event()

        self.thread_log.connect(self.append_log)
        self.manifest_loaded.connect(self._on_manifest)

        self._build_ui()
        self.refresh_manifest()

    # ---------------- UI ----------------

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)

        # 页面标题（QSS: PageTitle / PageSubtitle）
        t = QLabel("官方文件下载")
        t.setObjectName("PageTitle")
        s = QLabel("从 Mojang 官方清单下载客户端，SHA-1 与文件大小双校验后安装")
        s.setObjectName("PageSubtitle")
        lay.addWidget(t)
        lay.addWidget(s)

        # ---- 游戏目录卡片 ----
        card = QFrame()
        card.setObjectName("Card")
        c = QVBoxLayout(card)
        c.setContentsMargins(14, 14, 14, 14)
        c.setSpacing(10)

        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择 .minecraft 文件夹…")
        browse = QPushButton("浏览…")
        browse.setObjectName("PrimaryButton")
        browse.clicked.connect(self.choose_dir)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        c.addLayout(row)

        # 过滤
        f = QHBoxLayout()
        self.cb_release = QCheckBox("正式版")
        self.cb_release.setChecked(True)
        self.cb_snapshot = QCheckBox("快照")
        self.cb_snapshot.setChecked(True)
        self.cb_beta = QCheckBox("旧版 Beta")
        self.cb_alpha = QCheckBox("旧版 Alpha")
        for w in (self.cb_release, self.cb_snapshot, self.cb_beta, self.cb_alpha):
            f.addWidget(w)
            w.toggled.connect(self.refresh_list)
        f.addStretch()
        c.addLayout(f)

        # 代理
        prow = QHBoxLayout()
        prow.addWidget(QLabel("代理(可选)："))
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("如 http://127.0.0.1:7890")
        prow.addWidget(self.proxy_edit, 1)
        c.addLayout(prow)
        lay.addWidget(card)

        # ---- 清单状态 + 快捷操作 ----
        mrow = QHBoxLayout()
        self.manifest_label = QLabel("版本清单：未加载")
        self.manifest_label.setObjectName("BrandSubtitle")
        mrow.addWidget(self.manifest_label, 1)
        btn_refresh = QPushButton("刷新清单")
        btn_refresh.clicked.connect(self.refresh_manifest)
        btn_latest_release = QPushButton("下载最新正式版")
        btn_latest_release.clicked.connect(lambda: self.quick_latest("release"))
        btn_latest_snapshot = QPushButton("下载最新快照")
        btn_latest_snapshot.clicked.connect(lambda: self.quick_latest("snapshot"))
        for b in (btn_refresh, btn_latest_release, btn_latest_snapshot):
            mrow.addWidget(b)
        lay.addLayout(mrow)

        # ---- 版本列表 ----
        self.version_list = QListWidget()
        self.version_list.itemDoubleClicked.connect(lambda _i: self.start_download())
        lay.addWidget(self.version_list, 1)

        # ---- 操作行 ----
        ops = QHBoxLayout()
        self.btn_download = QPushButton("下载选中版本")
        self.btn_download.setObjectName("PrimaryButton")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.cb_json = QCheckBox("同时写入 version JSON（PCL 启动必需）")
        self.cb_json.setChecked(True)
        btn_open_dir = QPushButton("打开版本目录")
        btn_open_dir.clicked.connect(self.open_version_dir)
        ops.addWidget(self.btn_download)
        ops.addWidget(self.btn_cancel)
        ops.addWidget(self.cb_json)
        ops.addStretch()
        ops.addWidget(btn_open_dir)
        lay.addLayout(ops)

        # ---- 进度条 ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        # ---- 日志（带级别颜色）----
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(230)
        lay.addWidget(self.log_view)

        self.btn_download.clicked.connect(self.start_download)
        self.btn_cancel.clicked.connect(self.cancel_download)

    # ---------------- 行为 ----------------

    def choose_dir(self):
        initial = self.dir_edit.text().strip() or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "选择游戏目录（.minecraft 文件夹）", initial)
        if d:
            self.dir_edit.setText(d)

    def open_version_dir(self):
        game_dir = self.dir_edit.text().strip()
        if not game_dir:
            QMessageBox.warning(self, "提示", "请先选择游戏目录。")
            return
        target = os.path.join(game_dir, "versions")
        os.makedirs(target, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                os.system('xdg-open "%s" >/dev/null 2>&1 &' % target)
        except Exception as e:
            self.append_log("err", "无法打开目录：%s" % e)

    def append_log(self, level, msg):
        color = {"ok": "#81c784", "warn": "#ffb74d", "err": "#e57373",
                 "info": "#E8E8E8"}.get(level, "#E8E8E8")
        safe = html.escape(msg)
        self.log_view.append('<span style="color:%s">%s</span>' % (color, safe))

    def refresh_manifest(self):
        """先展示本地缓存，再后台拉取官方最新清单。"""
        cached = mc_core.load_manifest_cache()
        if cached:
            self.manifest_loaded.emit(cached)

        def job():
            try:
                opener = mc_core.build_opener(self.proxy_edit.text().strip() or None)
                m = mc_core.fetch_json(opener, mc_core.MANIFEST_URL)
                mc_core.save_manifest_cache(m)
                self.manifest_loaded.emit(m)
            except mc_core.NetError as e:
                self.thread_log.emit("err", "刷新官方版本清单失败：%s" % e)
                if not mc_core.load_manifest_cache():
                    self.thread_log.emit("err", "且本地无清单缓存，请检查网络后点击“刷新清单”。")

        threading.Thread(target=job, daemon=True).start()

    def _on_manifest(self, manifest):
        self.manifest = manifest
        self.versions_all = list(manifest.get("versions", []))
        latest = manifest.get("latest", {})
        self.manifest_label.setText(
            "共 %d 个版本 ｜ 最新正式版 %s ｜ 最新快照 %s" %
            (len(self.versions_all),
             latest.get("release", "?"),
             latest.get("snapshot", "?")))
        self.refresh_list()

    def refresh_list(self):
        types = {
            "release": self.cb_release.isChecked(),
            "snapshot": self.cb_snapshot.isChecked(),
            "old_beta": self.cb_beta.isChecked(),
            "old_alpha": self.cb_alpha.isChecked(),
        }
        self.versions_shown = [v for v in self.versions_all
                               if types.get(v.get("type"), False)]
        self.version_list.clear()
        for v in self.versions_shown:
            tag = mc_core.TYPE_NAMES.get(v.get("type"), v.get("type", "?"))
            self.version_list.addItem("%-24s [%s]" % (v["id"], tag))

    def quick_latest(self, vtype):
        if not self.manifest:
            self.append_log("warn", "清单尚未加载，请先刷新清单。")
            return
        vid = (self.manifest.get("latest") or {}).get(vtype)
        if not vid:
            self.append_log("warn", "清单中未找到最新%s。" % mc_core.TYPE_NAMES.get(vtype, vtype))
            return
        for i, v in enumerate(self.versions_shown):
            if v["id"] == vid:
                self.version_list.setCurrentRow(i)
                self.start_download()
                return
        # 不在当前过滤列表 → 直接下载
        for v in self.versions_all:
            if v["id"] == vid:
                self.append_log("info", "“%s”未在当前过滤中，已自动下载。" % vid)
                self._run_download(v)
                return
        self.append_log("warn", "清单中未找到版本 %s。" % vid)

    def start_download(self):
        row = self.version_list.currentRow()
        if row < 0 or row >= len(self.versions_shown):
            QMessageBox.information(self, "提示",
                                    "请先在列表中选择一个版本。\n\n也可直接点击“下载最新正式版 / 下载最新快照”。")
            return
        self._run_download(self.versions_shown[row])

    def _run_download(self, version):
        if self.worker and self.worker.isRunning():
            self.append_log("warn", "当前有任务进行中，请稍候。")
            return
        game_dir = self.dir_edit.text().strip()
        if not game_dir:
            QMessageBox.warning(self, "提示", "请先选择游戏目录（.minecraft 文件夹）。")
            return
        if not os.path.isdir(game_dir):
            QMessageBox.warning(self, "提示", "所选目录不存在或不是文件夹：\n%s" % game_dir)
            return

        proxy = self.proxy_edit.text().strip() or None
        self.cancel_evt.clear()
        self.append_log("info", "======== 开始处理版本 %s ========" % version["id"])

        self.worker = DownloadWorker(
            version, game_dir, proxy, self.cb_json.isChecked(), self.cancel_evt, self)
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(lambda v: self.progress.setValue(int(v * 100)))
        self.worker.done_signal.connect(self.on_done)
        self.worker.start()

        self.btn_download.setEnabled(False)
        self.btn_cancel.setEnabled(True)

    def cancel_download(self):
        self.cancel_evt.set()
        self.append_log("warn", "正在取消…")
        self.btn_cancel.setEnabled(False)

    def on_done(self, ok, vid):
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if ok:
            QMessageBox.information(
                self, "完成",
                "版本 %s 安装完成。\n\n文件位置：\n<游戏目录>/versions/%s/%s.jar\n\n"
                "在 PCL 中刷新/重启后即可看到该版本。" % (vid, vid, vid))
        else:
            self.append_log("err", "失败：%s（详见日志）" % vid)


# ============================================================
# 页面二：已安装扫描页
# ============================================================
class InstalledPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)

        t = QLabel("已安装版本")
        t.setObjectName("PageTitle")
        s = QLabel("扫描游戏目录 versions 下的版本状态（正常 / 缺 JAR / 缺 JSON）")
        s.setObjectName("PageSubtitle")
        lay.addWidget(t)
        lay.addWidget(s)

        card = QFrame()
        card.setObjectName("Card")
        c = QVBoxLayout(card)
        c.setContentsMargins(14, 14, 14, 14)
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择 .minecraft 文件夹…")
        btn_scan = QPushButton("扫描")
        btn_scan.setObjectName("PrimaryButton")
        btn_scan.clicked.connect(self.do_scan)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(btn_scan)
        c.addLayout(row)
        lay.addWidget(card)

        self.result_list = QListWidget()
        lay.addWidget(self.result_list, 1)

    def do_scan(self):
        game_dir = self.dir_edit.text().strip()
        if not game_dir:
            QMessageBox.warning(self, "提示", "请先选择游戏目录（.minecraft 文件夹）。")
            return
        if not os.path.isdir(game_dir):
            QMessageBox.warning(self, "提示", "所选目录不存在或不是文件夹：\n%s" % game_dir)
            return
        self.result_list.clear()
        result = mc_core.scan_installed_versions(game_dir)
        if not result:
            self.result_list.addItem("（未发现版本目录）")
            return
        ok_n = sum(1 for _, st in result if st == "正常")
        self.result_list.addItem("共 %d 个版本，正常 %d 个" % (len(result), ok_n))
        for vid, status in result:
            self.result_list.addItem("%-28s %s" % (vid, status))


# ============================================================
# 主窗口：左侧边栏 + 页面堆栈（复刻 main_ui.py 结构）
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minecraft 原版官方文件下载工具 v2.0")
        icon = icon_path()
        if icon:
            self.setWindowIcon(QIcon(icon))

        root = QWidget()
        root.setObjectName("RootWidget")
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ---- 左侧边栏（objectName 对齐 theme.py 的 QSS）----
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(250)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(20, 28, 20, 22)
        sl.setSpacing(6)

        brand = QLabel("BX STUDIO")
        brand.setObjectName("BrandTitle")
        sub = QLabel("MC Official Downloader")
        sub.setObjectName("BrandSubtitle")
        sl.addWidget(brand)
        sl.addWidget(sub)
        sl.addSpacing(26)

        # ---- 页面堆栈 ----
        self.stack = QStackedWidget()
        self.download_page = DownloadPage()
        self.installed_page = InstalledPage()
        self.stack.addWidget(self.download_page)
        self.stack.addWidget(self.installed_page)

        # ---- 导航按钮（QSS: NavButton；QButtonGroup 互斥高亮）----
        nav_download = QPushButton("下载")
        nav_download.setObjectName("NavButton")
        nav_download.setCheckable(True)
        nav_download.setChecked(True)
        nav_download.clicked.connect(lambda: self.stack.setCurrentWidget(self.download_page))

        nav_installed = QPushButton("已安装")
        nav_installed.setObjectName("NavButton")
        nav_installed.setCheckable(True)
        nav_installed.clicked.connect(lambda: self.stack.setCurrentWidget(self.installed_page))

        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(nav_download)
        grp.addButton(nav_installed)

        sl.addWidget(nav_download)
        sl.addWidget(nav_installed)
        sl.addStretch()

        status = QLabel("SHA-1 + 大小双校验 · 失败保护已有文件")
        status.setObjectName("BrandSubtitle")
        status.setWordWrap(True)
        sl.addWidget(status)

        root_lay.addWidget(sidebar)
        root_lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)


def main():
    # 任务栏 logo 关键：AppUserModelID 必须在创建 QApplication 之前设置
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BXStudio.MCOfficialDownloader.2")
    except Exception:
        pass

    app = QApplication([])
    apply_dark_theme(app)                # 黑金主题：字体 + QSS 一次生效
    icon = icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))

    win = MainWindow()
    win.resize(980, 700)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
