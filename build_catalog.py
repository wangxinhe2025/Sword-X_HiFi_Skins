# -*- coding: utf-8 -*-
"""
Sword-X HiFi Skins — 生成 catalog.json，并把文件夹皮肤打成 ZIP。

用法（在仓库根目录）:
  python build_catalog.py
  python build_catalog.py --dry-run
  build_catalog.cmd

Windows 注意: 不要用 python3（常指向 Microsoft Store 占位符，退出码 9009 且不会生成文件）。
请用 python 或 py -3，或直接运行 build_catalog.cmd。

约定:
  - 扫描 ./skins 下的子文件夹与 .zip
  - 皮肤 id / 下载名 = 文件夹名或 zip 主文件名（不含扩展名）
  - 从 skin.json 读取管理器所需元数据
  - 写出仓库根目录 catalog.json（format: sword-x-skin-catalog/1）
  - 每条皮肤含 zip 的 sizeBytes 与 md5
  - 文件夹皮肤：压缩为 skins/<名>.zip 后删除文件夹（--dry-run 不删、不写盘）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SKINS_DIR = REPO_ROOT / "skins"
CATALOG_PATH = REPO_ROOT / "catalog.json"

# 与播放器 SkinCatalog 远程拉取一致（common 分支）
GITHUB_OWNER = "wangxinhe2025"
GITHUB_REPO = "Sword-X_HiFi_Skins"
GITHUB_BRANCH = "common"
RAW_ZIP_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
    f"{GITHUB_BRANCH}/skins/{{id}}.zip"
)

DEFAULT_ENGINE_MIN = 1
DEFAULT_DESIGN = 2160
DEFAULT_VERSION = "1.0.0"
DEFAULT_AUTHOR = "WANG XINHE"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def file_md5(path: Path) -> str:
    """计算文件 MD5（小写十六进制）。"""
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def json_string(text: str, key: str) -> str:
    """粗解析 skin.json 顶层字符串字段（标准 JSON 失败时的回退）。"""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if not m:
        return ""
    raw = m.group(1)
    return (
        raw.replace(r"\\", "\\")
        .replace(r"\"", '"')
        .replace(r"\/", "/")
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
    )


def json_int(text: str, key: str, fallback: int) -> int:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+)', text)
    if not m:
        return fallback
    try:
        v = int(m.group(1))
        return v if v > 0 else fallback
    except ValueError:
        return fallback


def looks_like_skin_json(text: str) -> bool:
    return '"sword-x-skin/1"' in text or '"format"' in text and "sword-x-skin/1" in text


def find_skin_json_in_zip(zf: zipfile.ZipFile) -> tuple[str, str] | None:
    """返回 (archive_path, text)。优先包根 skin.json，否则一层子目录。"""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    # 规范化
    def norm(n: str) -> str:
        return n.replace("\\", "/")

    names = [norm(n) for n in names]
    for n in names:
        if n.lower() == "skin.json" or n.lower().endswith("/skin.json"):
            depth = n.count("/")
            if depth <= 1:
                raw = zf.read(n)
                return n, read_text_bytes(raw)
    # 再试任意深度的 skin.json（取最短路径）
    candidates = [n for n in names if n.lower().endswith("skin.json")]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s.count("/"), len(s)))
    n = candidates[0]
    return n, read_text_bytes(zf.read(n))


def load_skin_json_object(text: str) -> dict:
    """优先标准 JSON；失败再用正则抽字段。"""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return {}


def meta_from_skin_json(text: str, skin_id: str) -> dict:
    if not looks_like_skin_json(text):
        raise ValueError("not sword-x-skin/1")
    obj = load_skin_json_object(text)
    if obj:
        fmt = str(obj.get("format", ""))
        if fmt and fmt != "sword-x-skin/1":
            raise ValueError(f"bad format: {fmt}")
        title = str(obj.get("title") or skin_id)
        version = str(obj.get("version") or DEFAULT_VERSION)
        author = str(obj.get("author") or DEFAULT_AUTHOR)
        engine_min = int(obj.get("engineMin") or DEFAULT_ENGINE_MIN)
        design = int(obj.get("designShortEdge") or DEFAULT_DESIGN)
        if engine_min <= 0:
            engine_min = DEFAULT_ENGINE_MIN
        if design <= 0:
            design = DEFAULT_DESIGN
    else:
        title = json_string(text, "title") or skin_id
        version = json_string(text, "version") or DEFAULT_VERSION
        author = json_string(text, "author") or DEFAULT_AUTHOR
        engine_min = json_int(text, "engineMin", DEFAULT_ENGINE_MIN)
        design = json_int(text, "designShortEdge", DEFAULT_DESIGN)
    return {
        "id": skin_id,
        "title": title,
        "version": version,
        "author": author,
        "designShortEdge": design,
        "engineMin": engine_min,
        "sizeBytes": 0,
        "md5": "",
        "downloadUrl": RAW_ZIP_URL.format(id=skin_id),
    }


def read_folder_skin(folder: Path) -> dict:
    skin_json = folder / "skin.json"
    if not skin_json.is_file():
        raise FileNotFoundError("missing skin.json")
    text = read_text_bytes(skin_json.read_bytes())
    meta = meta_from_skin_json(text, folder.name)
    # 文件夹尚未打包时用内容合计作参考；正式 catalog 以 zip 体积 / md5 为准
    total = 0
    for path in folder.rglob("*"):
        if path.is_file() and path.name not in {".DS_Store", "Thumbs.db"}:
            total += path.stat().st_size
    meta["sizeBytes"] = int(total)
    meta["md5"] = ""
    return meta


def read_zip_skin(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path, "r") as zf:
        found = find_skin_json_in_zip(zf)
        if not found:
            raise FileNotFoundError("skin.json not in zip")
        _, text = found
        meta = meta_from_skin_json(text, zip_path.stem)
    meta["sizeBytes"] = int(zip_path.stat().st_size)
    meta["md5"] = file_md5(zip_path)
    return meta


def pack_folder_to_zip(folder: Path, zip_path: Path) -> None:
    """把文件夹内容打到 zip 根下（zip 内直接是 skin.json，无多余顶层目录名）。"""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            # 跳过常见垃圾
            if path.name in {".DS_Store", "Thumbs.db"} or path.name.startswith("._"):
                continue
            rel = path.relative_to(folder).as_posix()
            zf.write(path, rel)


def verify_zip_is_skin(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        found = find_skin_json_in_zip(zf)
        if not found:
            raise ValueError("packed zip has no skin.json")
        _, text = found
        if not looks_like_skin_json(text):
            raise ValueError("packed zip skin.json invalid")


def convert_folders(dry_run: bool) -> list[str]:
    """文件夹 → zip，成功后删文件夹。返回处理过的皮肤 id。"""
    converted: list[str] = []
    if not SKINS_DIR.is_dir():
        eprint(f"missing skins dir: {SKINS_DIR}")
        return converted

    for entry in sorted(SKINS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        skin_id = entry.name
        zip_path = SKINS_DIR / f"{skin_id}.zip"
        try:
            meta = read_folder_skin(entry)
        except Exception as ex:
            eprint(f"[skip folder] {skin_id}: {ex}")
            continue

        print(f"[pack] {skin_id}/ → skins/{skin_id}.zip")
        if dry_run:
            converted.append(skin_id)
            continue

        # 先打到临时文件，校验后再替换
        with tempfile.TemporaryDirectory() as td:
            tmp_zip = Path(td) / f"{skin_id}.zip"
            pack_folder_to_zip(entry, tmp_zip)
            verify_zip_is_skin(tmp_zip)
            # 再读一遍元数据确认
            _ = read_zip_skin(tmp_zip)
            shutil.copy2(tmp_zip, zip_path)

        shutil.rmtree(entry)
        print(f"[removed] skins/{skin_id}/")
        converted.append(skin_id)
        _ = meta  # 已用于校验文件夹可读
    return converted


def collect_entries() -> list[dict]:
    entries: list[dict] = []
    if not SKINS_DIR.is_dir():
        return entries

    for entry in sorted(SKINS_DIR.iterdir()):
        if entry.is_file() and entry.suffix.lower() == ".zip":
            skin_id = entry.stem
            try:
                meta = read_zip_skin(entry)
                entries.append(meta)
                print(
                    f"[zip] {skin_id}: title={meta['title']!r} "
                    f"version={meta['version']!r} author={meta['author']!r} "
                    f"design={meta['designShortEdge']} engineMin={meta['engineMin']} "
                    f"size={meta['sizeBytes']} md5={meta['md5']}"
                )
            except Exception as ex:
                eprint(f"[skip zip] {entry.name}: {ex}")
        elif entry.is_dir() and not entry.name.startswith("."):
            # dry-run 时文件夹可能还在
            try:
                meta = read_folder_skin(entry)
                entries.append(meta)
                print(
                    f"[folder] {entry.name}: title={meta['title']!r} "
                    f"version={meta['version']!r} author={meta['author']!r} "
                    f"design={meta['designShortEdge']} engineMin={meta['engineMin']} "
                    f"size~={meta['sizeBytes']} md5=(after zip)"
                )
            except Exception as ex:
                eprint(f"[skip folder] {entry.name}: {ex}")

    # 同 id 去重（优先 zip 扫描顺序已覆盖；若 folder+zip 并存保留后者 zip）
    by_id: dict[str, dict] = {}
    for e in entries:
        by_id[e["id"]] = e
    return [by_id[k] for k in sorted(by_id.keys(), key=lambda s: s.lower())]


def write_catalog(entries: list[dict], dry_run: bool) -> None:
    catalog = {
        "format": "sword-x-skin-catalog/1",
        "skins": entries,
    }
    text = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    print(f"[catalog] {len(entries)} skin(s) → {CATALOG_PATH}")
    if dry_run:
        print(text)
        return
    CATALOG_PATH.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Sword-X skin catalog and zip folders.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印，不写 catalog、不压缩/删除文件夹",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print(f"repo:  {REPO_ROOT}")
    print(f"skins: {SKINS_DIR}")
    print(f"out:   {CATALOG_PATH}")
    print(f"branch raw: {GITHUB_BRANCH}")

    convert_folders(dry_run=args.dry_run)
    entries = collect_entries()
    if not entries:
        eprint("no skins found")
        write_catalog([], dry_run=args.dry_run)
        return 1
    write_catalog(entries, dry_run=args.dry_run)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
