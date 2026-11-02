# 模块

## nxlib 标准层（14 模块，221 个公开 API）

用例不得复制配方，只能 `import nxlib`。注册与引导代码在 `scripts/nxlib/__init__.py` 的 `from . import` 区块，引导片段（`__file__` 缺失时回退 `sys.argv[0]`）写在文件头 docstring 里（`scripts/nxlib/__init__.py` 的 docstring 引导段）。

<!-- roster: nxlib -->
| 模块 | 职责 | 入口 | 行数 |
|---|---|---|---|
| `testing` | 用例框架：`say` 逐行 flush、`stage` 包阶段、`check` 逐项累加、`stage_finish`/`check_finish` 出口 | `stage` / `check` | 75 |
| `session` | 部件生命周期：统一 `new_part` 签名（内存件/落盘件）、`set_work`、`save_checked` | `new_part` | 73 |
| `modeling` | 建模配方：块、表达式、草图、拉伸、孔、倒圆、阵列、布尔、面查找、包盒、滚边刀 | `block` / `extrude` / `make_sketch_dims` | 1014 |
| `assembly` | 装配：加组件、单位阵、原型面查找、`Touch` 约束网络 | `add_component` / `touch_pair` | 98 |
| `drafting` | 制图：视图查询、UF 表格、PDF 导出、剖视配方 | `export_pdf` / `new_section_view` | 201 |
| `measure` | 只读测量：面表、同轴分组、孔锥参数、STL 截面面积与 IoU（`cut_plan` 偏移口径）、G0–G9 验收、件间比对 | `verify_parts` / `compare_parts` | 3285 |
| `rolling` | 滚球角网：边几何、±R 偏置坍缩判类、解析环带、直边刀 | `apply_roll_general` / `classify_corner` | 998 |
| `template` | 参数化模板：schema/参数表 → 命名表达式 → 局部编辑矩阵 | `param_table` / `edit_check` | 357 |
| `reverse` | 逆向测量编译：候选结构目录、全集站表、接口表、圆角跑道、结构表校验 | `candidate_directory` / `station_plan_full` | 683 |
| `structure_inference` | 结构推断：面图与角色、平面族/厚度带、同轴孔链、模板选择、未解析清单 | `infer_structures` / `face_graph` / `plan_validation_stations` | 1116 |
| `skeleton` | 骨架层：局部坐标系 `Frame`、二维轮廓曲线、基准轴与面 | `Frame` / `loop_uv` | 172 |
| `structures` | 构造层：参数（表达式）与数据（实测）分离的通用 builder + 结构级 builder（孔链 / 双瓣耳 / 叉耳 / 平面修边 / 逐边圆角账本 / 变截面放样 / 拔模窗口） | `revolved_profile` / `plate_2p5d` / `hole_chain` | 1265 |
| `transitions` | 过渡规划：参考圆角跑道 → 机制决策（面圆角/滚边/滚球/测量截面）+ 逐跑道可达性与拓扑证据（支撑面宽度、二面角）；G7 的 BLOCKED 只认这里的 `evidence` | `plan_runway` / `transitions_plan` | 283 |
| `audit` | 审计层：活性、局部性、特征预算、全集站表 G1full、包络偏差、编辑包络 | `liveness` / `locality` / `g1full` / `edit_envelope` | 765 |

三层关系（逆向域专用）：`reverse` 产出表 → `skeleton`/`structures` 按表建几何 → `audit` 复核"几何是否真的跟着参数动"。分层口径写在各自 docstring：`structures` 只吃 `(frame, design 表达式名, data 字面量)`，`data` 永不建表达式（`scripts/nxlib/structures.py` 的 docstring（"每个 builder 只吃"）、`scripts/nxlib/skeleton.py` 的 docstring（"data 永不建表达式"））。

`measure` 是最大的模块（3285 行），因为它同时承载四条测量链：面表、STL 截面、双向偏差、G 系列验收。解析面类型约定写在 docstring 里：圆柱 16、圆锥 17、圆环 19、平面 22（`scripts/nxlib/measure.py` 的 docstring（面类型约定））。

## 工具脚本

<!-- roster: scripts -->
| 文件 | 作用 | 依赖 |
|---|---|---|
| `scripts/check_journal.py` | 单个 journal 的静态检查：语法 (Py3.6)、占位符、20 组已固化坑位 | 纯标准库 |
| `scripts/check_repo.py` | 仓库自检八组：PY36 / COVERAGE / DOCS / TREE / NOLIB / CONCISE / ROUTE / WIKI | 纯标准库 |
| `scripts/run_journal_batch.bat` | 单件批处理：`NX_HOME` 解析 + workdir + `ugiicmd` + `run_journal.exe` | NX 12 |
| `scripts/gb_drawing.py` | 国标成套出图模块：图框、标题栏、技术要求、尺寸道位、PDF | NX 12（journal 内 import） |
| `scripts/render/export_stl.py` | NX 内导出 STL，读 `IMG_PART`/`IMG_OUT` | NX 12 |
| `scripts/render/render_stl.py` | 宿主侧 STL 着色渲染：Z 缓冲 + 二面角 25° 特征边 | numpy + Pillow |
| `scripts/render/pdf2png.py` | PDF 首页栅格化 | pymupdf |
| `scripts/render/condition.py` | 裁边、限制最大尺寸、按边车重画比例尺 | Pillow |

两个 `.bat` 的共同约束：必须纯 ASCII，因为 cmd 按 GBK 解析（`SKILL.md` §2）。

## 8 个域文档

<!-- roster: references -->
| 文件 | 域 | 结构 | 对应用例 |
|---|---|---|---|
| `modeling.md` | 建模：方法论 §1（含草图驱动 §1.13、拔模与分段回转 §1.14）、特征配方 §2、阵列/镜像 §3、螺纹 §4、可编辑性 §6 | 809 行 | 01 02 03 14 15 22 28 32 34 37 47 |
| `assembly.md` | 装配：组件 §A.1、配对约束 §A.2、组件阵列 §A.3、运动连接 §A.5、自检 §A.6 | 167 行 | 04 10 16 17 29 35 |
| `drafting.md` | 工程图：图纸/三视图 §B.1、投影 §B.4、剖视、出图导出 §B.3、装配图 §B.6 | 212 行 | 06 20 21 31 |
| `drafting-annotation.md` | 标注：全局偏好 §2、尺寸道位 §3、UF 尺寸配方 §4、注释 §5、表格 §6、球标 §6b、中心线 §7 | 280 行 | 19 |
| `gb-drawing.md` | 国标标准件 `gb_drawing.py` 的调用骨架与 API 速查 | 187 行 | 33 |
| `fea.md` | 有限元：CAD→FEM §1、材料与 PSOLID §2、壳 §3a、CTETRA §4、SIM 与解算方案 §5-6a、求解 §7 | 288 行 | 09 24 25 30 |
| `motion.md` | 运动仿真：Link §M.2、运动副 §M.3、驱动 §M.4、连接件 §M.5a、求解 §M.6、结果 §M.7、静不定 §M.8 | 321 行 | 18 23 36 |
| `reverse-engineering.md` | 逆向：流程 §1、结构表 §1.1、草图-拉伸 §2、分层基线 §3、验收门 §4、过渡 §9、测量链 §10、参数化模板 §11、测量编译 §12 | 656 行 | 38 39 40 41 42 43 44 45 46 47 48 49 |

域文档之间不互相引用成链：`reverse-engineering.md` 把构造配方推给 `modeling.md`，自己不重复 API；`drafting.md` 把标注规则推给 `drafting-annotation.md`（`references/drafting.md` 抬头）。这种"只指路不复制"的写法让每个域的配方只有一处权威，代价是读跨域任务要读多个文件。

## 模块改动的影响面

改某个 nxlib 模块会波及哪些用例（按用例文件里的 `from nxlib.X import` / `import nxlib.X` 实算，`testing` 只统计非自包含用例）：

| 模块 | 依赖它的用例 | 数量 |
|---|---|---|
| `testing` | 01 02 03 04 06 07 09 10 18 19 20 21 22 23 24 25 26 27 29 30 31 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 | 38 |
| `session` | 01 02 03 04 10 14 15 16 20 22 24 25 26 27 29 30 33 34 35 37 38 39 40 41 42 43 44 45 46 47 | 30 |
| `modeling` | 01 02 03 04 10 14 15 16 20 21 22 26 27 29 31 33 34 35 37 38 39 40 41 43 44 46 47 | 27 |
| `drafting` | 19 20 21 31 | 4 |
| `measure` | 38 39 41 42 43 45 48 49 | 8 |
| `template` | 41 42 43 44 45 46 47 48 | 8 |
| `skeleton` | 42 43 44 45 46 47 | 6 |
| `structures` | 42 43 44 45 46 47 | 6 |
| `assembly` | 04 10 35 | 3 |
| `audit` | 43 44 45 46 48 | 5 |
| `reverse` | 42 45 48 49 | 4 |
| `structure_inference` | 49 | 1 |
| `rolling` | 40 | 1 |

越靠上游（`testing`/`session`/`modeling`）改动面越大，必须跑全量；`rolling`/`reverse`/`audit` 只影响尾部用例，可以先跑相关 gate 再跑全量确认。

## 用例的三种结构

| 形态 | 出口 | 适用 |
|---|---|---|
| `stage()` 逐阶段 | 全部 `STAGE_OK` 后打 `TESTxx_DONE`；失败打 `TESTxx_FAIL stages=[...]` | 流程型用例（06 07 19 20 21 31 32） |
| `check()` 逐项累加 | 单条失败只打 `REG_xxx=FAIL`，末尾统一判 | 断言型用例（22-30、38-49） |
| 单一 benchmark 出口 | 直接打 `BENCH_PASS` / `CONSTRAINT_PASS` | 09 10 16 18 36 |

第二种形态有一处刻意的设计：**单条失败不打 `_FAIL`**。原因是 `:gate` 用 `findstr /C:"_FAIL"` 扫全文，若每条失败都是 `_FAIL`，用例内层的预期失败（如 26 号的 ThreadedHole 崩溃探针）会误触门。所以逐项失败的 token 是 `REG_xxx=FAIL`，只有末尾汇总的 `TESTxx_FAIL` 才带 `_FAIL`（`scripts/tests/README.md` §运行方式（`REG_xxx=FAIL` 段））。

## 探针与自包含用例

7 个用例不用 nxlib，名单登记在 `check_repo.py` 的 `SELF_CONTAINED`（`scripts/check_repo.py` 的 `SELF_CONTAINED`）。它们是有意的例外：探针的价值在原样记录调用方式，改成库调用反而失真（`scripts/check_repo.py` 的 `SELF_CONTAINED` 注释）。3 个一次性探针（11/12/13）连 gate 都不进（`scripts/check_repo.py` 的 `PROBES`）。

新增同类探针必须显式登记，否则 `check_repo.py` 的 NOLIB 组会把它判成"配方被复制进用例"。
