# -*- coding: utf-8 -*-
"""交付件离线普查与门（STEP / STL / DXF / PMI）。

设计约束：
  - 只依赖标准库即可导入；ezdxf 只在 `dxf_census` 内惰性导入。
  - 语法保持 Python 3.6（NX 12 内嵌解释器），同时可在宿主 3.11+ 运行。
  - 判定分三态：PASS / FAIL / NO_SIGNAL。依赖缺失或仪器看不见时给
    NO_SIGNAL，绝不把"没测到"写成 PASS。
  - 错误码统一 `DELIV_E_*`，供 CLI 与用例断言。

事实表 facts（由 NX 侧 journal 落盘）：
    {"bodies": 1, "solid_bodies": 1, "faces": 7, "edges": 14,
     "volume": 9497.3452, "schema": "AP242", "pmi": {"FLATNESS_TOLERANCE": 1}}
"""
import math
import os
import re

from stl_math import read_stl_triangles

# ---------------------------------------------------------------- 通用

PASS = "PASS"
FAIL = "FAIL"
NO_SIGNAL = "NO_SIGNAL"


def _result(verdict, codes, notes=None):
    return {"verdict": verdict, "codes": list(codes), "notes": list(notes or [])}


def _fail(codes, notes=None):
    return _result(FAIL, codes, notes)


def _pass(notes=None):
    return _result(PASS, [], notes)


def _no_signal(codes, notes=None):
    return _result(NO_SIGNAL, codes, notes)


# ---------------------------------------------------------------- STEP

_STEP_ENTITY_RE = re.compile(
    r"(?m)^\s*#(\d+)\s*=\s*(?:\(\s*)?([A-Z][A-Z0-9_]*)\s*\(")
_STEP_REF_RE = re.compile(r"#(\d+)")
_STEP_SCHEMA_RE = re.compile(
    r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", re.I)


def _step_schema(text):
    m = _STEP_SCHEMA_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    if "{" in name:
        name = name.split("{", 1)[0].strip()
    return name


def step_census(path):
    """数 STEP 实体并检查引用完整性。

    返回 dict：schema / size / entities / counts / dangling / pmi / notes。
    `entities` 是 "#id" -> 类型 的映射，供需要逐实体定位的调用方使用。
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8", "replace")
    schema = _step_schema(text)
    entities = {}
    counts = {}
    for m in _STEP_ENTITY_RE.finditer(text):
        eid = int(m.group(1))
        typ = m.group(2).upper()
        entities[eid] = typ
        counts[typ] = counts.get(typ, 0) + 1
    defined = set(entities)
    # STEP 字符串字面量用单引号包裹，串内 '#' 不是实体引用，先剔串。
    unquoted = re.sub(r"'[^']*'", "''", text)
    referenced = set(int(x) for x in _STEP_REF_RE.findall(unquoted))
    dangling = sorted(referenced - defined)

    pmi_types = {}
    for typ in counts:
        if typ.endswith("_TOLERANCE") or typ in (
                "GEOMETRIC_ITEM_SPECIFIC_USAGE", "DRAUGHTING_MODEL",
                "DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION",
                "SHAPE_DIMENSION_REPRESENTATION", "DATUM_FEATURE",
                "DATUM_SYSTEM", "DATUM_TARGET"):
            pmi_types[typ] = counts[typ]

    empty_draughting = len(re.findall(
        r"DRAUGHTING_MODEL\s*\([^;]*?,\s*\(\s*\)\s*\)", text, re.S))

    return {
        "path": os.path.abspath(path),
        "size": len(raw),
        "schema": schema,
        "entities": entities,
        "counts": counts,
        "n_entities": len(entities),
        "dangling": dangling,
        "pmi": pmi_types,
        "empty_draughting_models": empty_draughting,
        "solid_breps": counts.get("MANIFOLD_SOLID_BREP", 0),
        "advanced_faces": counts.get("ADVANCED_FACE", 0),
        "edge_curves": counts.get("EDGE_CURVE", 0),
        "nauo": counts.get("NEXT_ASSEMBLY_USAGE_OCCURRENCE", 0),
        "products": counts.get("PRODUCT", 0),
    }


def step_gate(census, facts=None, schema=None, pmi=None):
    """STEP 门：实体数与 B-rep 事实相等，空骨架直接拦。

    facts 为 None 时只做结构检查（空件 / 悬空引用 / schema）。
    pmi 为 {类型: 最小数量} 时要求对应子类型存在。
    """
    codes, notes = [], []
    if census["n_entities"] == 0:
        return _fail(["DELIV_E_STEP_EMPTY"], ["no entity at all"])
    if census["solid_breps"] == 0:
        codes.append("DELIV_E_STEP_EMPTY")
        notes.append("0 MANIFOLD_SOLID_BREP (legal-looking empty skeleton)")
    if census["dangling"]:
        codes.append("DELIV_E_STEP_DANGLING")
        notes.append("%d dangling refs" % len(census["dangling"]))
    if schema and schema.upper() not in (census["schema"] or "").upper():
        codes.append("DELIV_E_STEP_SCHEMA")
        notes.append("schema=%r expected %r" % (census["schema"], schema))
    if facts:
        for key, got, want in (
                ("solids", census["solid_breps"], facts.get("solid_bodies")),
                ("faces", census["advanced_faces"], facts.get("faces")),
                ("edges", census["edge_curves"], facts.get("edges"))):
            if want is None:
                continue
            if got != want:
                codes.append("DELIV_E_STEP_COUNT")
                notes.append("%s: census=%d facts=%d" % (key, got, want))
                break
    if pmi:
        for typ, want in pmi.items():
            got = census["pmi"].get(typ, 0)
            if got < want:
                codes.append("DELIV_E_STEP_PMI")
                notes.append("%s: census=%d expected>=%d" % (typ, got, want))
                break
    return _fail(codes, notes) if codes else _pass(notes)


# ---------------------------------------------------------------- STL

def _vsub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vcross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vnorm(a):
    return math.sqrt(_vdot(a, a))


def _weld_key(v, digits=6):
    return (round(v[0], digits), round(v[1], digits), round(v[2], digits))


class _UnionFind(object):
    def __init__(self):
        self.parent = {}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def add(self, x):
        if x not in self.parent:
            self.parent[x] = x

    def union(self, a, b):
        self.add(a)
        self.add(b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def stl_census(path, weld_digits=6):
    """STL 拓扑体检：水密/绕向/欧拉数/体积/分量/包盒/退化面。"""
    tris = read_stl_triangles(path)
    if not tris:
        return {"path": os.path.abspath(path), "triangles": 0,
                "watertight": False, "winding_consistent": False,
                "euler": None, "components": 0, "genus": None,
                "volume": 0.0, "area": 0.0, "bbox": None,
                "degenerate": 0, "vertices": 0, "edges": 0,
                "notes": ["no triangle"]}

    verts = {}
    faces = []
    degenerate = 0
    area = 0.0
    volume_signed = 0.0
    uf = _UnionFind()
    for _, v0, v1, v2 in tris:
        keys = []
        for v in (v0, v1, v2):
            k = _weld_key(v, weld_digits)
            if k not in verts:
                verts[k] = len(verts)
            keys.append(verts[k])
        faces.append(keys)
        cr = _vcross(_vsub(v1, v0), _vsub(v2, v0))
        a2 = _vnorm(cr)
        if a2 <= 1e-12:
            degenerate += 1
        area += 0.5 * a2
        # 有符号体积：divergence theorem，闭合且外法向时为正。
        volume_signed += _vdot(v0, _vcross(v1, v2)) / 6.0
        uf.add(keys[0])
        uf.union(keys[0], keys[1])
        uf.union(keys[1], keys[2])

    edges = {}
    for keys in faces:
        for a, b in ((keys[0], keys[1]), (keys[1], keys[2]),
                     (keys[2], keys[0])):
            edges[(a, b)] = edges.get((a, b), 0) + 1

    watertight = True
    winding = True
    for a, b in edges:
        if a > b:
            continue
        ab, ba = edges.get((a, b), 0), edges.get((b, a), 0)
        if ab + ba != 2:
            watertight = False
        if ab != 1 or ba != 1:
            winding = False

    roots = set(uf.find(k) for keys in faces for k in keys)
    n_components = len(roots)
    n_vertices = len(verts)
    n_edges = len(edges) // 2
    euler = n_vertices - n_edges + len(faces)
    genus = None
    if n_components and (2 * n_components - euler) % 2 == 0:
        genus = (2 * n_components - euler) // 2

    lo = [1e300, 1e300, 1e300]
    hi = [-1e300, -1e300, -1e300]
    for _, v0, v1, v2 in tris:
        for v in (v0, v1, v2):
            for i in range(3):
                lo[i] = min(lo[i], v[i])
                hi[i] = max(hi[i], v[i])

    return {
        "path": os.path.abspath(path),
        "triangles": len(tris),
        "vertices": n_vertices,
        "edges": n_edges,
        "watertight": watertight,
        "winding_consistent": winding,
        "euler": euler,
        "components": n_components,
        "genus": genus,
        "volume": abs(volume_signed),
        "volume_signed": volume_signed,
        "area": area,
        "bbox": [lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]],
        "degenerate": degenerate,
        "notes": [],
    }


def stl_gate(census, facts=None, volume_tol=0.001):
    """STL 门：水密 + 绕向 + 分量数 + 体积；χ 按 2C−2g 解释。"""
    codes, notes = [], []
    if census["triangles"] == 0:
        return _fail(["DELIV_E_STL_EMPTY"], ["no triangle"])
    if not census["watertight"]:
        codes.append("DELIV_E_STL_OPEN")
        notes.append("not watertight")
    if not census["winding_consistent"]:
        codes.append("DELIV_E_STL_WINDING")
        notes.append("inconsistent winding")
    if census["degenerate"]:
        codes.append("DELIV_E_STL_DEGENERATE")
        notes.append("%d degenerate faces" % census["degenerate"])
    if census["genus"] is None and census["watertight"]:
        codes.append("DELIV_E_STL_EULER")
        notes.append("euler=%r is not 2C-2g" % census["euler"])
    # 局部绕向一致不代表整体朝外：整体翻面后每条边仍是一正一反。
    # NX 的 STL 约定外法向，闭合网格有符号体积必须为正。
    if (census["watertight"] and census["winding_consistent"]
            and census["volume_signed"] <= 0.0):
        codes.append("DELIV_E_STL_ORIENTATION")
        notes.append("signed volume %.6f (inward orientation)"
                     % census["volume_signed"])
    if facts:
        want_bodies = facts.get("bodies")
        # 分量为壳数；一个实体带内腔时壳数 > 实体数，不算少体。
        if want_bodies is not None and census["components"] < want_bodies:
            codes.append("DELIV_E_STL_COMPONENTS")
            notes.append("components=%d < bodies=%d"
                         % (census["components"], want_bodies))
        want_vol = facts.get("volume")
        if want_vol:
            rel = abs(census["volume"] - want_vol) / abs(want_vol)
            if rel > volume_tol:
                codes.append("DELIV_E_STL_VOLUME")
                notes.append("volume %.6f vs %.6f (%.4f%%)"
                             % (census["volume"], want_vol, rel * 100.0))
    return _fail(codes, notes) if codes else _pass(notes)


# ---------------------------------------------------------------- DXF

def dxf_census(path):
    """DXF 审计：必须遍历全部布局，DIMENSION 常在 SHT1 而不是 msp。"""
    try:
        import ezdxf
    except ImportError:
        return {"path": os.path.abspath(path), "available": False,
                "reason": "ezdxf not installed", "layouts": {},
                "total": {}, "dimensions": 0}
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    layouts = {}
    total = {}
    for layout in doc.layouts:
        counts = {}
        for ent in layout:
            typ = ent.dxftype()
            counts[typ] = counts.get(typ, 0) + 1
            total[typ] = total.get(typ, 0) + 1
        layouts[layout.name] = counts
    return {
        "path": os.path.abspath(path),
        "available": True,
        "audit_errors": len(auditor.errors),
        "audit_fixes": len(auditor.fixes),
        "insunits": doc.header.get("$INSUNITS"),
        "measurement": doc.header.get("$MEASUREMENT"),
        "layouts": layouts,
        "total": total,
        "dimensions": total.get("DIMENSION", 0),
    }


def dxf_gate(census, expect_units=4, expect_dims=None):
    if not census.get("available", True):
        return _no_signal(["DELIV_E_DXF_UNAVAILABLE"],
                          [census.get("reason", "ezdxf missing")])
    codes, notes = [], []
    if census["audit_errors"]:
        codes.append("DELIV_E_DXF_AUDIT")
        notes.append("%d audit errors" % census["audit_errors"])
    if expect_units is not None and census["insunits"] != expect_units:
        codes.append("DELIV_E_DXF_UNITS")
        notes.append("$INSUNITS=%r expected %r"
                     % (census["insunits"], expect_units))
    if expect_dims is not None and census["dimensions"] < expect_dims:
        codes.append("DELIV_E_DXF_DIMS")
        notes.append("DIMENSION=%d expected>=%d"
                     % (census["dimensions"], expect_dims))
    return _fail(codes, notes) if codes else _pass(notes)


# ---------------------------------------------------------------- PMI

def pmi_gate(census, expected):
    """按 STEP 子类型族统计；泛型 GEOMETRIC_TOLERANCE 在 NX 输出里恒为 0。"""
    codes, notes = [], []
    for typ, want in sorted(expected.items()):
        got = census["pmi"].get(typ, 0)
        if got < want:
            codes.append("DELIV_E_PMI_MISSING")
            notes.append("%s=%d expected>=%d" % (typ, got, want))
    return _fail(codes, notes) if codes else _pass(notes)


# ---------------------------------------------------------------- 部件事实

def part_gate(facts):
    """最小部件事实门：0 实体 / 无实体文件一律拦（用于回读结果）。"""
    codes, notes = [], []
    if not facts:
        return _fail(["DELIV_E_PART_EMPTY"], ["no facts"])
    if not facts.get("bodies"):
        codes.append("DELIV_E_PART_EMPTY")
        notes.append("bodies=%r" % facts.get("bodies"))
    if facts.get("solid_bodies") == 0:
        codes.append("DELIV_E_PART_NO_SOLID")
        notes.append("solid_bodies=0")
    return _fail(codes, notes) if codes else _pass(notes)


# ---------------------------------------------------------------- 汇总

def gate_summary(results):
    """把多个门结果合成一个判决；NO_SIGNAL 不会升级成 PASS。"""
    codes, notes = [], []
    verdict = PASS
    for name, res in results.items():
        codes.extend(res["codes"])
        notes.extend("%s: %s" % (name, n) for n in res["notes"])
        if res["verdict"] == FAIL:
            verdict = FAIL
        elif res["verdict"] == NO_SIGNAL and verdict == PASS:
            verdict = NO_SIGNAL
    return _result(verdict, codes, notes)


def format_result(name, res):
    line = "%s=%s" % (name, res["verdict"])
    if res["codes"]:
        line += " codes=" + ",".join(res["codes"])
    for note in res["notes"]:
        line += " | " + note
    return line
