# Changelog

本文件记录 `nxopen-journal` 技能的版本变更。格式遵循
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [1.1.0] - 2026-10-19

### Added

- Motion 滑动副配方（`JointDefine.Type.Slider`，两组几何、关节局部 z 轴）与 36 号回归用例（偏置曲柄滑块，解析偏差 0.0013 mm）。
- Motion 齿轮连接件配方（`Couplers.CreateCouplerGearBuilder`，60 r/min 输入 → −30 r/min 输出）。
- `nxlib.modeling.involute_gear` 增加可选轮毂参数 `hub_d` / `hub_len` / `z_offset`，34 号用例覆盖体积增量。
- `gb_drawing.assembly_bbox(bodies)` 多组件包盒；`tech_note(..., base_y=)` 避开明细栏。
- `check_journal.py` 规则 5.19（`NXOpen.UF.UFDrf` 伪容器）与 `from math import dist` 形式的 Python 3.6 检测。
- `nxlib.testing.write_log()`：用例日志落盘（18/36 号此前日志恒为空）。

### Changed

- `references/motion.md`：补齐公共导入与 `set_expr`/`VC`/`RF` 约定；M.6 修正为 0 基帧模型（帧 0 = t=0），删除"首帧非 t=0 / 末帧重复或归零"的误判；M.7 按旋转轴给角度元素表并补线速度配方；M.5c 明确 `MotionTranslationZ` 沿关节局部 z 轴、正速度沿 −z。
- `references/motion.md`：澄清 Euler 驱动正值绕 +Z 为顺时针、`frame k ↔ t=k·T/nstep`、`atan2(R[1,0],R[0,0])` 只给相对设计位姿角（绝对角走 §M.4）、journal 内无 numpy（差分与 unwrap 手写）。
- 文档精简：`SKILL.md`、六个域文件与 `scripts/tests/README.md` 删除验证过程、日期、历史沿革和重复解释，只保留结论、配方与判据；`README.md` / `README.en.md` 去掉会随文档变动的实测计数，改为稳定的能力描述。
- `README.md` / `README.en.md`：孔包覆盖改为三种非螺纹孔型（螺纹用底孔+标注）；Motion 覆盖补滑动副与齿轮连接件；前置条件中的用例数改为 33 个带判定的用例。
- README 运动图按 0 基帧模型重新生成（720 步、721 帧；摆角跨度与解析解相差 0.0014°，换向 2 次）。
- 维护规则：新知识按“结论/做法”模板入库，禁止日期与过程叙述；`check_repo.py` 新增 CONCISE 组自动拦截，并保留“先合并后追加”的增长纪律（不设体积硬上限）。
- `references/assembly-drafting.md`：移动副改用两组平面 `Touch`；补轴环 + `Touch` 去轴向滑动；约束枚举补全并标注 `ValueOf` 非成员；`Matrix3x3` 字段组语义明确为局部轴分量。
- `references/gb-drawing.md`：导入骨架改为绝对路径插入 `sys.path`；装配图尺寸增加 PDF 文本层数值复核硬步骤。
- `references/modeling.md`：补相切工具体布尔失败；新增 §3.7 渐开线齿轮标准层入口。
- `references/drafting-annotation.md`：剖视图 placement origin 与内容中心的偏移说明。
- `nxlib.modeling.expressions` 增加 `unit_name` 参数，角度表达式可传 `"Angle"`（默认仍为 `"Length"`）。

### Fixed

- `RUN_TESTS.bat` 第 102 行 `exit /b 1call :gate 34...` 拼接，导致 34 号从未执行却仍打印 `ALL TESTS PASSED`。
- `check_repo.py` 覆盖正则未锚定行首，把上述畸形行误算为已覆盖。
- `gb_drawing.map_point` 在 `MapModelToDrawing` 失败时静默返回 `ref + xyz`，忽略投影与比例，导致尺寸/包盒静默错位。
- 球标 `CreateIdSymbol` 第 7 参必须为 `NXOpen.UF.Drf.Object` 结构体；文档原写法直接传 Edge 必失败。
- 装配实例边 + 剖视图上的线性尺寸可能静默读错（200→200.2、140→136.3），已写入复核要求。
- Motion 帧索引口径：`AskLinkTransfromForGivenFrame` 为 0 基（0..nfr-1，帧 0 = t=0）；修正 18/36 号用例与文档中"首帧是 t=dt、末帧重复"的误判（此前按 1..nfr 遍历，越界索引返回值被误读）。18 号用例的 CSV 同步改为 0 基并增加 `time_s` 列。
