# nxopen-journal 仓库 Wiki

面向维护者的代码导览。回答四个问题：这个仓库是什么、一次任务怎么跑通、模块怎么分工、哪些边界不能破。
agent 会话需要的是 `SKILL.md` 与 `references/`，本 wiki 不进 agent 的必读路径。

## 项目身份

| 项 | 值 |
|---|---|
| 形态 | agent 技能（`SKILL.md` + 域文档 + 脚本 + 回归套件），不是可执行程序、不是 Python 包 |
| 宿主 | Siemens NX 12（12.0.0.27），Windows 11；NX 安装根由环境变量 `NX_HOME` 指定 |
| journal 解释器 | NX 内嵌 Python 3.6.1，固定不可替换；宿主 Python 3.11+ 只跑检查与工具 |
| 产物 | `.prt` 模型、装配、Drafting PDF、Nastran 结果、STL 渲染图 |
| 验收 | 42 个批处理用例看输出 token；静态侧由 `check_repo.py` 与 `check_journal.py` 兜住 |

## 页面

| 页面 | 内容 |
|---|---|
| [架构](01-architecture.md) | 五层结构与依赖方向：入口层 → 域文档 → 工具脚本 → nxlib 标准层 → 回归套件 |
| [主执行流](02-execution-flow.md) | 一次请求从路由到 NX 回放的全链路，两套门（静态/动态）各自判什么 |
| [模块](03-modules.md) | nxlib 12 个模块、`scripts/` 工具、8 个域文档的职责与入口函数 |
| [数据流](04-data-flow.md) | 逆向测量编译链、FEA 链、出图链、离线渲染链、参数化模板链 |
| [边界与风险](05-boundaries.md) | Python 3.6.1、批处理能力上限、平台绑定、判据判别力 |

## 维护约定

- **改代码就改本 wiki，同一次提交**。范围：nxlib 模块、`references/*.md`、`scripts/` 下工具脚本、会话流程或门禁结构。`check_repo.py` 的 WIKI 组是这条的机器门——名册缺项、索引页漏链接、用例/gate 计数过期、行号锚点、指向已删符号或章节的引用，都会被拦。
- 新增/改名模块要补进对应 roster 表：模块页三张表前各有 `<!-- roster: nxlib|scripts|references -->` 标记，门只认标记后紧邻表格的首列。表被删或标记被删，对应项就报缺失。
- 锚点用符号名或 §章节，不用行号：行号每次改动都会漂移，而 wiki 带着错行号仍然能读，正是最难发现的过期形态。引用写成 `文件` 的 `符号名`，或 `文件` §章节号。
- 与 `SKILL.md` / `references/` 冲突时以那两处为准：它们是 agent 的执行依据，本 wiki 只描述实现现状。
- 本 wiki 允许日期与过程性表述（不受 CONCISE 组约束），但同一事实仍以一处为准，不复制域文档正文。
