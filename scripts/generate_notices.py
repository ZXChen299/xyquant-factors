"""Copy the locked build environment's original license notices without guessing them."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def markdown(value):
    return " ".join(str(value).split()).replace("|", "\\|")


def project_url(metadata):
    urls = []
    for item in metadata.get_all("Project-URL", []):
        if "," in item:
            label, url = item.split(",", 1)
            if url.strip().startswith(("https://", "http://")):
                urls.append((label.strip().lower(), url.strip()))
    for wanted in ("source", "source code", "repository", "github", "homepage", "home"):
        for label, url in urls:
            if label == wanted:
                return url
    home = metadata.get("Home-page", "")
    return home if home.startswith(("https://", "http://")) else (urls[0][1] if urls else None)


def is_notice(path):
    text = str(path).lower()
    name = Path(path).name.lower()
    return ".dist-info/" in text and (
        "/licenses/" in text or name.startswith(("license", "copying", "notice"))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--python-license", type=Path, required=True)
    parser.add_argument("--python-version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"3\.12\.\d+", args.python_version):
        parser.error("Supply the exact Python 3.12 patch version used to build the runtime.")
    site = args.site_packages.resolve(strict=True)
    distributions = {
        canonical(d.metadata["Name"]): d
        for d in importlib.metadata.distributions(path=[str(site)])
    }
    locked = []
    for line in (ROOT / "requirements-build.lock").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([\w.-]+)==([\w.+-]+)", line)
        if not match:
            raise SystemExit("Unsupported lock entry: " + line)
        name, version = match.groups()
        distribution = distributions.get(canonical(name))
        if distribution is None or distribution.version != version:
            raise SystemExit("Installed metadata does not match lock: " + line)
        notices = [item for item in distribution.files or [] if is_notice(item)]
        if not notices:
            raise SystemExit("No installed license notice was found for: " + line)
        locked.append((name, version, distribution, notices))

    # Validate all sources before creating any output. Sources are read-only.
    pending = []
    rows = []
    for name, version, distribution, notices in locked:
        metadata = distribution.metadata
        folder = Path("docs/licenses") / (canonical(name) + "-" + version)
        files = []
        for item in notices:
            relative = Path(str(item))
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit("Unsafe metadata license path: " + str(item))
            source = Path(distribution.locate_file(item)).resolve(strict=True)
            if not source.is_relative_to(site):
                raise SystemExit("License is outside the selected environment: " + str(item))
            target = folder / relative
            contents = source.read_bytes()
            pending.append((target, contents))
            files.append({"source": relative.as_posix(), "copy": target.as_posix(),
                          "sha256": hashlib.sha256(contents).hexdigest()})
        rows.append({"name": metadata["Name"], "version": version,
                     "license_expression": metadata.get("License-Expression"),
                     "license": metadata.get("License"),
                     "project_urls": metadata.get_all("Project-URL", []),
                     "home_page": metadata.get("Home-page"), "upstream_url": project_url(metadata),
                     "files": files})

    python_copy = Path("docs/licenses") / ("cpython-" + args.python_version) / "LICENSE.txt"
    python_contents = args.python_license.read_bytes()
    pending.append((python_copy, python_contents))
    inventory = {
        "source": "Installed wheel metadata from the environment matching requirements-build.lock",
        "lock_sha256": hashlib.sha256((ROOT / "requirements-build.lock").read_bytes()).hexdigest(),
        "python": {"version": args.python_version, "copy": python_copy.as_posix(),
                   "sha256": hashlib.sha256(python_contents).hexdigest()},
        "distributions": rows,
    }
    lines = [
        "# 第三方软件许可声明", "",
        "本清单由 `scripts/generate_notices.py` 从与 `requirements-build.lock` 完全匹配的已安装包元数据生成。",
        "版本、许可字段和项目链接均来自对应 wheel 的元数据；下列本地链接保留原始许可文本及版权声明，文件未经改写。",
        "", "锁文件同时包含客户端依赖与构建工具，因此本表是构建环境清单，不表示每个包都被收录进可执行文件。",
        "未声明许可字段时明确记录为未声明，以随包原文为准；本项目的 MIT 许可证不替代各第三方许可。",
        "", "原始元数据字段、wheel 内来源路径及每份文本的 SHA-256 见 [许可来源清单](docs/licenses/inventory.json)。",
        "", "## Python 运行环境", "",
        f"可执行文件使用 CPython {args.python_version}。分发保留 [Python 安装目录原始 LICENSE.txt]({python_copy.as_posix()})，其中包含 Python 及随附组件的许可声明。",
        "", "## 锁定的 Python 包", "",
        "| 包 | 版本 | 元数据中的许可 | 来源与原文 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        license_value = row["license_expression"] or row["license"] or "元数据未声明；见原始许可文本"
        links = ([f'[项目来源]({row["upstream_url"]})'] if row["upstream_url"] else [])
        for index, file in enumerate(row["files"], 1):
            label = Path(file["source"]).name if len(row["files"]) == 1 else str(index) + ":" + Path(file["source"]).name
            links.append(f'[{label}]({file["copy"]})')
        lines.append(f'| {markdown(row["name"])} | {markdown(row["version"])} | {markdown(license_value)} | ' + " · ".join(links) + " |")
    lines += ["", "## 构建工具的附加说明", "",
              "PyInstaller 的原始 `COPYING.txt` 包含 Bootloader Exception 及运行时 hooks 的许可说明。",
              "`pyinstaller-hooks-contrib` 的原始 `LICENSE` 区分标准构建 hooks 与运行时 hooks；请保留完整原文。",
              "pywin32 和 setuptools 安装包包含多份附属组件声明，本清单逐份复制，不将它们全部替换为包级许可名称。",
              "", "发布时应将本声明及 `docs/licenses/` 原文一并交付。修改依赖或 Python 版本后必须从新的构建环境重新生成。", ""]
    for path, contents in pending:
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    (ROOT / "docs/licenses/inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"packages": len(rows), "license_files": len(pending), "python": args.python_version}))


if __name__ == "__main__":
    main()
