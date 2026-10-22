#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 原版官方文件下载工具 · 核心逻辑层（无界面）
=====================================================
从旧版 mc_official_downloader.py 抽出，只保留纯逻辑，界面层见 mc_gui_qt.py（PySide6）。

功能：
  1. 从 Mojang 官方版本清单（version_manifest_v2.json）获取全部版本元数据；
  2. 下载客户端 JAR，校验 SHA-1 与文件大小，全部通过后才安装到正确版本目录；
  3. 下载/校验失败时保护已有文件：先写临时文件，校验成功后才原子替换；
  4. 可选写入 version JSON（PCL 启动该版本必需）；
  5. 可选 HTTP(S) 代理。

安装目标（官方目录结构，PCL2 兼容）：
  <游戏目录>/versions/<版本ID>/<版本ID>.jar
  <游戏目录>/versions/<版本ID>/<版本ID>.json
"""

import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
USER_AGENT = "MCOfficialDownloader/2.0 (Minecraft official file helper)"
DEFAULT_TIMEOUT = 30          # 元数据请求超时（秒）
DOWNLOAD_TIMEOUT = 60         # 下载读超时（秒）
CHUNK_SIZE = 64 * 1024        # 64KB 分块读写
RETRY_TIMES = 3               # 下载重试次数
CACHE_FILE_NAME = "manifest_cache.json"

TYPE_NAMES = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧版 Beta",
    "old_alpha": "旧版 Alpha",
}
TYPE_ORDER = ["release", "snapshot", "old_beta", "old_alpha"]


# ---------------------------------------------------------------------------
# 基础工具：路径 / 清单缓存
# ---------------------------------------------------------------------------

def app_base_dir():
    """程序所在目录（打包后为 EXE 所在目录，便于便携式运行）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def cache_file_path():
    """清单缓存路径：优先程序目录（便携），不可写时退回用户主目录。"""
    base = app_base_dir()
    path = os.path.join(base, CACHE_FILE_NAME)
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except OSError:
        fallback_dir = os.path.join(os.path.expanduser("~"), ".mc_official_downloader")
        os.makedirs(fallback_dir, exist_ok=True)
        return os.path.join(fallback_dir, CACHE_FILE_NAME)


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
