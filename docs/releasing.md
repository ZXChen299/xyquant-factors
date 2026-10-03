# 构建、检查与固定版本发布

本文面向维护者。客户安装随包的 Windows 程序，不执行这些构建步骤。发布仓库为 [`ZXChen299/xyquant-factors`](https://github.com/ZXChen299/xyquant-factors)，当前程序版本为 `v0.2.0-rc.1`。下文保留 `v0.1.0-rc.1` 作为历史流程示例；创建新发布时必须使用未发布的新版本，不能重复创建或改写现有标签。

## 生成候选构建

在独立的本项目仓库中操作，使用 Windows x64 和 Python 3.12。不要把包含服务器密钥、客户资料的外层工作区作为发布仓库。

```powershell
py -3.12 -m venv .work/build-env
.\.work\build-env\Scripts\python.exe -m pip install -r requirements-build.lock
.\.work\build-env\Scripts\python.exe -B -m unittest discover -s client -p "test_*.py"
```

先使用实际构建环境生成第三方声明，再构建程序。参数中的版本和 Python 许可证文件必须来自该次构建使用的 Python 安装：

```powershell
.\.work\build-env\Scripts\python.exe -B scripts/generate_notices.py --site-packages .work/build-env/Lib/site-packages --python-license "<Python安装目录>/LICENSE.txt" --python-version "<实际3.12补丁版本>"
.\.work\build-env\Scripts\python.exe -B scripts/build.py
.\.work\build-env\Scripts\python.exe -B scripts/check_release.py
```

许可证生成器验证每个锁定包的已安装版本，复制原始许可文本，输出来源路径和 SHA-256。不得将输出中的未声明许可字段凭印象补成 MIT。`scripts/build.py` 生成 `bin/FactorBridge.exe`、程序校验文件和 `release.json`，并把声明与许可原文复制进插件子目录，保证市场安装也包含这些文本。因此必须在构建前运行声明生成器。

## 发布前的实际验收

正式稳定版应完成干净 Windows 用户环境中的市场安装、工具发现、浏览器授权、真实对话查询和文件下载。测试版可以在清楚列明未完成场景的前提下发布为预发布版本。记录 Codex 版本、插件版本、账号隔离检查、相对文件路径与 SHA-256。未执行或被审批、网络阻断的项目标记“未完成”；隔离 Codex 配置不能记为干净 Windows 用户环境。

检查更新记录与验收记录所述版本一致。运行包的 `release.json`、程序校验文件与实际程序必须匹配；源码摘要须对应被打包的源码。插件中不存储用户凭据或导出数据。检查器使用发布清单及已知凭据标记检查，不能替代人工审阅文件清单。

## 创建固定版本并打包

以下命令以测试版 `v0.1.0-rc.1` 为例。保留候选状态与未完成项，GitHub Release 必须标记为预发布，不创建 `v0.1.0` 稳定版标签。提交前运行检查器，人工审阅 `git status --short` 和待提交文件。仅从独立 `xyquant-factors` 仓库添加已检查的发布内容。

```powershell
git status --short
git diff --check
git add README.md LICENSE CHANGELOG.md THIRD_PARTY_NOTICES.md .gitignore .gitattributes requirements-build.lock .agents client plugins scripts docs
git diff --cached --stat
git commit -m "Prepare XYQuant Factors 0.1.0-rc.1"
git tag -a v0.1.0-rc.1 -m "XYQuant Factors 0.1.0-rc.1 prerelease"
git archive --format=zip --prefix=xyquant-factors-0.1.0-rc.1/ --output=.work/xyquant-factors-0.1.0-rc.1.zip v0.1.0-rc.1
Get-FileHash -Algorithm SHA256 -LiteralPath .work/xyquant-factors-0.1.0-rc.1.zip
```

发布包从固定 Git 标签生成，仅包含标签中跟踪的文件。发布前确认标签包含程序本体、原始第三方许可、源码和实际验收记录。不要覆盖已经交付的标签或替换同名发布包；修复使用新版本、新标签及新校验值。

## 推送 GitHub

确认远端为已建立的独立客户端仓库，然后推送对应提交和不可变版本标签：

```powershell
git remote -v
git push origin HEAD
git push origin v0.1.0-rc.1
```

在 GitHub 对该标签创建标记为 **Pre-release** 的 Release，附加 `.work/xyquant-factors-0.1.0-rc.1.zip`、SHA-256、更新说明和验收记录。版本包 SHA-256 作为 Release 独立校验文件提供，不把它回写到已打包的标签内容，以免更改被校验的包。

市场来源用于发现插件，发布基准是有明确验收记录的固定标签。客户教程使用 `--ref v0.1.0-rc.1` 固定该测试版本，不跟随开发分支的变化；本地 Codex 帮助已确认支持该参数。测试版不以稳定版名义交付，完整验收后再发布稳定版本并提供对应标签的升级说明。保留旧版本标签供回退，程序不自行下载更新并执行。

## 仅文档更新

当业务源码、构建产物和线上服务已经一致，README、使用说明及后续验收结果可以单独提交到 `main`。执行发布边界检查、相对链接检查和差异审阅后推送，再核验远端实际提交。Release 说明可以链接补充后的在线验收记录，但保留原标签、EXE、ZIP 和校验文件，不为说明更新重打包或重部署服务。固定发布包内的文档仍是原快照，应明确区别于 `main` 上的最新说明。

发布后分别核验提交检查／工作流、发布资产摘要和线上健康状态；没有运行的 CI 记为未运行，不能把本地测试等同于 CI 成功。

## 可选 GitHub Actions

截至 2026-10-03，仓库未配置启用的 GitHub Actions 工作流，当前版本以已记录的本地测试和线上验收为依据。`scripts/github-actions-verify.yml` 是尚未启用的 Windows CI 模板；如后续需要启用，由维护者在具备相应工作流权限后放入 `.github/workflows/verify.yml` 并核验执行结果。客户安装插件不需要此步骤。
