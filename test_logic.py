#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心逻辑端到端测试：使用真实 Mojang 官方源验证下载-校验-安装-保护链路。"""
import hashlib
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mc_core as mod  # noqa: E402

TEST_VERSION = "b1.8.1"   # 旧版 Beta，客户端 JAR 约 4.9MB，适合测试
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))


def main():
    opener = mod.build_opener(None)

    print("== 1. 获取官方版本清单 ==")
    manifest = mod.fetch_json(opener, mod.MANIFEST_URL)
    versions = manifest["versions"]
    check("清单包含 versions", isinstance(versions, list) and len(versions) > 100,
          "共 %d 个版本" % len(versions))
    check("latest.release 非空", bool(manifest.get("latest", {}).get("release")))
    target = next((v for v in versions if v["id"] == TEST_VERSION), None)
    check("找到测试版本 %s" % TEST_VERSION, target is not None)

    print("== 2. 版本元数据 SHA-1 校验 ==")
    raw, vjson = mod.fetch_version_raw(opener, target["url"], target.get("sha1"))
    check("版本 JSON SHA-1 与清单一致",
          hashlib.sha1(raw).hexdigest() == target["sha1"].lower())
    client = vjson["downloads"]["client"]
    check("客户端 JAR 元数据完整",
          bool(client.get("url")) and bool(client.get("sha1")) and client.get("size"),
          "size=%d sha1=%s" % (client["size"], client["sha1"][:12] + "..."))

    work = tempfile.mkdtemp(prefix="mc_dl_test_")
    game_dir = os.path.join(work, ".minecraft")
    os.makedirs(game_dir)
    vdir = os.path.join(game_dir, "versions", TEST_VERSION)
    os.makedirs(vdir)
    jar_path = os.path.join(vdir, TEST_VERSION + ".jar")

    def prog(done, total):
        pass

    try:
        print("== 3. 下载 + 校验 + 安装 ==")
        t0 = time.time()
        mod.install_client_jar(opener, game_dir, TEST_VERSION, client,
                               progress_cb=prog, log_cb=lambda m: print("    LOG:", m))
        dt = time.time() - t0
        check("JAR 已安装", os.path.isfile(jar_path))
        check("JAR 大小正确", os.path.getsize(jar_path) == client["size"],
              "%d / %d" % (os.path.getsize(jar_path), client["size"]))
        check("JAR SHA-1 正确", mod.sha1_of_file(jar_path) == client["sha1"].lower())
        check("无残留 .part 文件", not os.path.exists(jar_path + ".part"))
        print("    耗时 %.1fs" % dt)

        print("== 4. 重复执行：已存在且有效 → 跳过下载 ==")
        mtime_before = os.path.getmtime(jar_path)
        mod.install_client_jar(opener, game_dir, TEST_VERSION, client,
                               progress_cb=prog, log_cb=lambda m: print("    LOG:", m))
        check("文件未被重写（跳过）", os.path.getmtime(jar_path) == mtime_before)

        print("== 5. 失败保护：下载失败时保留已有文件 ==")
        # 先把目标文件破坏为“用户原有文件”，再模拟下载失败
        with open(jar_path, "wb") as f:
            f.write(b"user-existing-file-do-not-touch")
        orig_bytes = open(jar_path, "rb").read()

        _orig_download = mod.download_to_file

        def _fail_download(*a, **k):
            raise mod.NetError("模拟网络中断")

        mod.download_to_file = _fail_download
        try:
            mod.install_client_jar(opener, game_dir, TEST_VERSION, client,
                                   progress_cb=prog, log_cb=lambda m: print("    LOG:", m))
            check("应抛出错误", False, "未抛错")
        except mod.NetError as e:
            check("下载失败被捕获", True, str(e)[:60])
        finally:
            mod.download_to_file = _orig_download  # 恢复原函数（勿用 del）
        check("失败后已有文件未受损", open(jar_path, "rb").read() == orig_bytes)
        check("失败后无 .part 残留", not os.path.exists(jar_path + ".part"))

        print("== 6. 失败保护：SHA-1 校验失败时保留已有文件 ==")
        bad = client.copy()
        bad["sha1"] = "0" * 40
        try:
            mod.install_client_jar(opener, game_dir, TEST_VERSION, bad,
                                   progress_cb=prog, log_cb=lambda m: print("    LOG:", m))
            check("应抛出错误", False, "未抛错")
        except mod.NetError as e:
            check("校验失败被捕获", True, str(e)[:60])
        check("校验失败后已有文件未受损", open(jar_path, "rb").read() == orig_bytes)
        check("校验失败后无 .part 残留", not os.path.exists(jar_path + ".part"))

        print("== 7. 损坏文件修复：目标已损坏时重新下载并替换 ==")
        with open(jar_path, "wb") as f:
            f.write(b"corrupt-corrupt-corrupt")
        mod.install_client_jar(opener, game_dir, TEST_VERSION, client,
                               progress_cb=prog, log_cb=lambda m: print("    LOG:", m))
        check("损坏文件已被正确文件替换", mod.sha1_of_file(jar_path) == client["sha1"].lower())

        print("== 8. version JSON 写入 ==")
        mod.install_version_json(opener, game_dir, TEST_VERSION, target["url"],
                                 target.get("sha1"), log_cb=lambda m: print("    LOG:", m))
        json_path = os.path.join(vdir, TEST_VERSION + ".json")
        check("JSON 已写入", os.path.isfile(json_path))
        with open(json_path, "rb") as f:
            check("JSON 字节与官方一致（SHA-1）",
                  hashlib.sha1(f.read()).hexdigest() == target["sha1"].lower())

        print("== 9. 扫描已安装版本 ==")
        res = mod.scan_installed_versions(game_dir)
        check("扫描结果", res and res[0][0] == TEST_VERSION, str(res))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n========== 汇总 ==========")
    failed = [n for n, ok, _ in PASS if not ok]
    for n, ok, d in PASS:
        if not ok:
            print("  FAILED:", n, d)
    print("通过 %d / %d" % (len(PASS) - len(failed), len(PASS)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
