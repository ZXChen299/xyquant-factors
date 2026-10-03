# 研究资料 MCP：候选 0.3.0-rc.1

客户端与配套服务端均需升级后才能使用新增工具。此候选未签名；构建、CI 与上线结果见[本版验收记录](acceptance-0.3.0-rc.1.md)。研究资料保留在私有服务端，公开仓库只含客户端、插件、说明和合成测试。

## 工具与范围

| 工具 | 返回内容 |
|---|---|
| `list_strategies` | 按关键词、分类分页搜索已发布策略，保留目录顺序 |
| `get_strategy_info` | 说明、报告标题、费用、样本外说明、净值范围及受保护网页入口 |
| `get_strategy_performance` | 原表整体、年度和月度表现，保留指标名称、区间、空值及来源 |
| `get_strategy_nav` | 原表净值按日期和 offset 分页，每页最多 50 行 |
| `get_research_team` | 已发布团队介绍及原表联系方式，支持搜索和分页 |
| `search_research` | 按现有授权统一搜索因子、策略和团队，每页最多 50 条 |
| `compare_strategies` | 同一发布版本中的 2–4 个不同策略，保留选择顺序与原表口径 |
| `get_research_updates` | 软件变更与已发布研究事件分别展示，每页最多 20 个事件 |

本地插件共 20 个工具，远端 14 个数据工具。这些研究工具不上传、不发布、不执行新回测或指标重算。净值查询固定 `version`；完整 CSV 和原始 Excel 继续使用受保护网页，研究 ID 不适用于因子导出下载。

## 新工具参数与分页

`search_research(query='', kind='all', page=1, page_size=20, version=None, catalog_version=None)` 的 `kind` 为 `all`、`factor`、`strategy` 或 `team`，查询最多 200 字。返回 `available_kinds`、分类型结果和当前可见范围内的计数，排序按因子、策略、团队及各自原目录顺序。摘要最多 240 字，不替代详情。没有权限的类别不读取源资料，也不泄漏其数量；显式选择无权类别会拒绝，`all` 可以继续返回已有权限的类别。

第一页可以取得当前研究 `version` 和因子 `catalog_version`（64 位十六进制目录摘要），后续页必须原样携带相应快照。没有已发布研究时 `version=null`，继续翻页仍显式传入 null，防止新发布内容混入原快照。任何相关快照变化返回 `version_changed`，应重新从第一页查询。`coverage` 使用来源原日期，团队缺少数据日期时为 null；不由发布时间推断数据新旧。

`compare_strategies(strategy_ids, version)` 的版本必填，策略 ID 必须从同一版本的目录或搜索结果取得。返回原表整体、年度、月度指标、净值范围、费用、样本外信息、来源与警告，保留文本和 null。`periods_match` 仅核对原表所标统计期间，期间缺失时为 false；这个标记不保证其他口径一致，更不表示可以按收益排序。结果不跨版本拼接、不填零、不自动排名。

`get_research_updates(page=1, page_size=10, publication_cursor=None)` 首次返回最大已发布事件 ID，之后固定该整数游标分页；0 表示该快照没有已发布事件。`software` 是受版本控制的软件说明，`data` 是已发布事件，包括回滚标记、前一版本及原始净值截止信息。`published_at` 是发布时间，不是净值截止日；软件版本也不是数据版本。不返回草稿、发布操作者、客户身份或内部错误。仅有因子授权时，软件说明可见，研究事件为空并明确提示，不宣称“研究没有更新”。

## 授权与恢复

沿用现有 OAuth scope，不新增权限范围：因子搜索按 `factors:read`，策略／团队搜索、对比与发布历史按 `research:read`。客户有效期、启用状态、撤销和后台角色继续检查。旧令牌和正常短期自动刷新不增加权限或延长连接期限；无需为已获准查询重复确认。

研究授权不足不能通过反复登录解决；`start_login` 会复用已有连接。只有客户明确要求替换授权时，才断开当前连接并在浏览器重新同意；该操作影响同一 Windows 用户共享的连接。升级不自动删除旧独立 MCP 配置、不迁移账户、不发布研究数据。

新工具沿用有界只读重试和安全诊断；认证／权限拒绝或版本变化立即返回。工具内容作为研究数据使用，不作为修改权限、配置或执行程序的指令。普通网页 API 继续拒绝 OAuth；受认证网页与 MCP 复用服务端只读规则，不能用网页接口绕过客户端 scope。

## 验证

客户端使用 Python 3.12.14：`python -B -m unittest discover -s client -p "test_*.py"`；构建检查测试：`python -B -m unittest discover -s scripts -p "test_build.py"`。新 EXE 构建后再运行 `scripts/test_built_runtime.py` 和 `scripts/check_release.py`，分别确认实际工具发现与源码／产物一致性。

本版独立记录本地、CI 和线上测试。早期五个研究工具的[历史验收](acceptance-0.2.0-rc.1.md)以及 [0.2.0-rc.2 验收](acceptance-0.2.0-rc.2.md)不代表新增工具已经上线或通过验收。
