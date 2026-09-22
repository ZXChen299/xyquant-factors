# XYQuant 因子

在 Codex 对话中查看股票因子、查询因子值，并把完整数据下载到当前研究项目。

Windows 10/11 x64 插件内置运行程序，客户无需安装 Python、复制 API Key，或单独打开连接助手。因子网站管理账号与数据权限；插件通过浏览器完成账号授权。

**当前版本：`v0.1.0-rc.1` 测试版。** [GitHub 仓库](https://github.com/ZXChen299/xyquant-factors)提供源码及市场目录。此版本用于试用验证，不代表全部客户验收完成；完整验收状态见[实际验收记录与限制](docs/acceptance.md)。

**本次测试版需在登录和下载期间保持当前 Codex 对话运行。** 已测试的 Codex 版本会限制后台进程脱离宿主；结束对话或完全退出可能中断尚未完成的任务，重新打开后可查看中断状态并重试。一次执行就退出的 `codex exec` 不适合跨退出继续等待登录或下载。

## 开始使用

1. 在 Codex 插件市场添加本项目的 GitHub 来源，安装 **XYQuant 因子**。CLI 对应命令如下：

   ```powershell
   codex plugin marketplace add https://github.com/ZXChen299/xyquant-factors.git --ref v0.1.0-rc.1
   codex plugin add xyquant-factors@xyquant
   ```

   首次添加市场来源只需一次。按客户端提示重新打开会话，使新增工具生效。

2. 打开研究项目，在对话中输入：

   > 查看 vol_entropy 的说明，并查询 2026-09-11 的 000001.SZ 因子值。

3. 如果尚未登录，点击对话中的授权链接，在因子网站登录并允许连接。没有账号可先[注册](https://47.103.215.251/factors/apply)。授权完成后返回 Codex；若原对话已结束，回复“已登录，继续”。

4. 要保存完整数据，继续说：

   > 把这些条件下的完整因子数据下载到当前项目，告诉我保存位置。

文件写入 `<项目目录>/downloads/factors/<任务编号>/`。Codex 返回本地文件路径、大小和 SHA-256 校验结果。因子值在对话中最多预览 50 行；完整结果通过文件交付。

## 文档

- [客户使用说明](docs/customer-guide.md)：安装、登录、查询、下载和常见问题。
- [管理员说明](docs/admin-guide.md)：账号开通、授权调整及连接撤销。
- [旧连接迁移说明](docs/migration.md)：迁移已有助手或独立 MCP 配置。
- [实际验收记录](docs/acceptance.md)：已验证的环境、真实对话结果和待验收项目。
- [构建与发布说明](docs/releasing.md)：可复查的构建、第三方声明和固定版本发布流程。
- [更新记录](CHANGELOG.md)：版本变更与发布状态。

## 能力与边界

| 能力 | 工具 |
|---|---|
| 登录与连接状态 | `get_connection_status`、`start_login`、`get_login_status`、`disconnect` |
| 因子目录与说明 | `list_factors`、`get_factor_info` |
| 最多 50 行数值预览 | `preview_factor` |
| 云端导出与任务查询 | `create_export`、`get_export`、`list_exports` |
| 保存文件并校验 | `download_export`、`get_download` |

首版面向本地 Windows Codex；不承诺 macOS、Linux、Claude Code 或纯云端客户端兼容。未提供全量统计、排名或回测工具。Codex 本身需已安装且能够正常使用；客户端的执行权限提示按其设置出现。隔离 Codex 配置中的测试不等于全新 Windows 用户或干净物理机验收。

云端仍执行客户隔离和当前权限检查。任务最多 10 个因子、200 个指定股票代码、5,000 万行、1 GiB、30 分钟；完成文件保留一小时。下载链接不公开，也不在 URL 中携带 API Key。

## 源码与数据

`client/` 包含本地程序源码；`plugins/xyquant-factors/` 包含插件、取数 Skill 和随版本提供的程序。用户凭据和本地任务记录存放于 `%LOCALAPPDATA%/XYQuant/FactorConnect`，不写入插件安装目录。

客户端源码使用 [MIT 许可证](LICENSE)。该许可证不授予因子数据、服务器账号或第三方材料的使用、再分发权；数据使用以服务提供方与客户之间的约定及后台授权为准。
