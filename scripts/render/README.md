# 离线出图链（NX 批处理截不了图时的替代路线）

NX 12 批处理会话导不出图像（实测 2026-09-23：UF 截图路线内存访问违例，
Gateway builder 提交成功但不写文件），所以三维实体的 README 级图件走
"导 STL → 宿主离线渲染"链，工程图走 "Drafting PDF → 宿主栅格化"链。
本目录是这两条链的全部脚本（宿主脚本依赖 Python 3 + numpy + Pillow +
pymupdf；`export_stl.py` 是 NX 内运行的 journal）。

## 链路

```mermaid
graph LR
  A[.prt] -->|"export_stl.py<br>(NX 内, IMG_PART/IMG_OUT)"| B[.stl]
  B --> C[render_stl.py<br>着色+特征边]
  C --> D[condition.py<br>裁边+比例尺+限宽]
  P[.prt + Drafting] --> E[gb_drawing.export_pdf<br>或 19 号用例路线]
  E --> F[pdf2png.py<br>pymupdf 栅格化]
  F --> D
```

三维件：`run_export.bat part.prt out.stl` → `render_stl.py scene.json` →
`condition.py in.png out.png 1500 1100 14`。工程图：NX 里出 PDF →
`pdf2png.py in.pdf out.png 3.0` → `condition.py` 同样收尾。

## 逐件用法

- **run_export.bat** `<abs .prt> <abs .stl> [workdir]`——env 转发的 wrapper。
  必须经它传参：Git Bash 里 `\\$var` 在双引号内会吃掉反斜杠、journal 收到
  字面 `$n`（实测）；环境变量必须在 cmd 侧 set。日志写在 STL 同目录
  `export_stl.log`，NX 吞掉控制台输出时证据在这里。
- **export_stl.py**（NX journal）——读 `IMG_PART`/`IMG_OUT`；三角公差
  `ChordalTol=0.01`（0.05 在 README 渲染尺寸下圆柱面可见棱面；NX 12 的
  STLCreator 没有 TriangleTolerance）；装配无自身体时回退
  `Scope.EntirePart`。
- **render_stl.py** `<scene.json>` 或 CLI 参数——Z 缓冲平面着色 + 二面角
  25° 特征边，效果对齐 NX"带边着色"视图。场景键：顶层
  `out/w/h/az/el/palette/scalebar`，`parts[]` 每件
  `stl/color/alpha/rotate_z/translate/split_bodies/palette/body_alphas`
  （拆连通体时逐体取调色板与透明度）。CLI 覆盖：
  `render_stl.py in.stl out.png [w] [h] [--az A] [--el E] [--scalebar MM TEXT]`。
  渲染后在 `<out>.scalebar.json` 写比例尺边车（世界长度、像素、渲染盒），
  `condition.py` 裁剪后据它重画比例尺——不写边车，裁剪会把比例尺挪离
  真实位置。
- **pdf2png.py** `<in.pdf> <out.png> [zoom]`——首页栅格化；工程图审计用
  3.0（A4 得约 2526×1786）。
- **condition.py** `<in.png> <out.png> [max_w] [max_h] [pad]`——按非白包围盒
  裁边、白边 pad 像素、限制最大像素；有边车时裁剪后在底部 40px 白条内重画
  比例尺。工程图（有图框）一般不裁（pad 给大些或跳过），三维渲染裁。

## 出图后校验

不要拿渲染 PNG 眼测布局——显示缩放会骗人。工程图数值审计用 pymupdf：
`get_drawings()` 拿线段/圆、`get_text('words')` 拿文字（NX 连字符抽出来是
软连字符 U+00AD、中文抽不出来——按位置与线段核，对 `\xad` 归一化）。
19 号用例的 `scripts/tests/verify_anno_pdf.py` 是现成的复核模板。

## 视角配方（az/el，2026-09-28 实测标定）

`--az` 是绕 z 的方位角，`--el` 是模型绕 x 的后仰角。**el 语义与直觉相反：
正值会把模型翻成倒挂**（实测 el=45 开始翻、60/65 凸台朝下孔口朝上），
正常视角一律用负值或默认。以建模支座（凸台+双筋板+四孔底板）实测：

| 视角 | 参数 | 实测效果 |
| --- | --- | --- |
| 正三轴测（NX TfrTri 风，README 主图推荐） | `--az 45 --el -60` | 凸台朝上，顶面+前侧+右侧三面可见，立体感最强 |
| 正等测（TfrIso 风） | `--az 45 --el -55` | 三轴比例更均匀，介于等测与三轴测之间 |
| 纯顶视（孔位/布局图） | `--az 45 --el 0` | xy 面无变形，孔位分布一张看清 |
| 前视方位三轴测 | `--az 0 --el -60` | 底板长边朝前 |
| 侧视方位三轴测 | `--az 90 --el -60` | 底板短边朝前 |
| 默认（不传参） | az=38 el=27 | 陡俯视，顶面占画面——README 主图不要用它 |

两条配套纪律（同日实测）：

- `render_stl.py` 出图后**必须跑 `condition.py`**：比例尺只写在
  `<out>.scalebar.json` 边车里，`condition.py` 裁边时才真正画上去；
  漏跑 = 图上没有比例尺（装配图实测踩过）。
- 装配多件分色走 scene.json 的 `parts[].color`（实测灰/金/深灰/红四件
  同图可辨）；单件 CLI 直渲用不到。
