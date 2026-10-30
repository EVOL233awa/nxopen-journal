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

- 结论必须能在仓库里指到位置：本 wiki 每条判断附带 `文件:行号`，行号随代码移动会漂移，函数名才是稳定锚点。
- 与 `SKILL.md` / `references/` 冲突时以那两处为准：它们是 agent 的执行依据，本 wiki 只描述实现现状。
- 新增顶层目录或改模块职责时同步本目录；`check_repo.py` 的 TREE 组只校验 `SKILL.md` §8 清单覆盖磁盘顶层条目，不校验本 wiki 内容。
- 本 wiki 允许日期与过程性表述（不受 CONCISE 组约束），但同一事实仍以一处为准，不复制域文档正文。
