# -*- coding: utf-8 -*-
"""骨架层：局部坐标系、二维轮廓曲线、基准轴/面。

设计/数据分层口径（整件与组件共用）：

* ``design`` —— 命名表达式，由特征 builder 消费；改值 → DoUpdate 即改几何。
* ``data``   —— 实测轮廓点、实测轴/定位点、方向向量；字面值，改它必须重测
  重放，文档与 schema 里必须披露。**data 永不建表达式**，否则就是死表达式。

Frame 只做坐标换算，不建特征；基准轴/面的坐标一律按 data 层处理（NX12
里 datum 点不能绑表达式，见 P0 能力矩阵）。
"""
import math

import NXOpen

from .session import _cross as _session_cross, _dot, _unit as _session_unit


class Frame(object):
    """右手局部系 (u, v, z)，world = origin + u*U + v*V + z*Z。"""

    def __init__(self, origin=(0.0, 0.0, 0.0), u=(1.0, 0.0, 0.0),
                 v=(0.0, 1.0, 0.0), z=(0.0, 0.0, 1.0)):
        self.origin = [float(x) for x in origin]
        self.U = _unit(u)
        self.V = _unit(v)
        self.Z = _unit(z)
        err = max(abs(_dot(self.U, self.V)), abs(_dot(self.U, self.Z)),
                  abs(_dot(self.V, self.Z)))
        if err > 1e-6:
            raise ValueError("frame axes are not orthogonal: %.3e" % err)

    @classmethod
    def from_azimuth(cls, az_deg, origin=(0.0, 0.0, 0.0)):
        """径向 U（方位角 az_deg，绕 +Z）、切向 V（逆时针 90°）、+Z。"""
        a = math.radians(float(az_deg))
        ca, sa = math.cos(a), math.sin(a)
        return cls(origin, (ca, sa, 0.0), (-sa, ca, 0.0), (0.0, 0.0, 1.0))

    def vec(self, u, v, z):
        return (self.U[0] * u + self.V[0] * v + self.Z[0] * z,
                self.U[1] * u + self.V[1] * v + self.Z[1] * z,
                self.U[2] * u + self.V[2] * v + self.Z[2] * z)

    def pt(self, u, v, z):
        w = self.vec(u, v, z)
        return NXOpen.Point3d(self.origin[0] + w[0], self.origin[1] + w[1],
                              self.origin[2] + w[2])

    def vec3(self, u, v, z):
        w = self.vec(u, v, z)
        return NXOpen.Vector3d(w[0], w[1], w[2])

    def to_local(self, p):
        d = (p[0] - self.origin[0], p[1] - self.origin[1],
             p[2] - self.origin[2])
        return (_dot(d, self.U), _dot(d, self.V), _dot(d, self.Z))

    def describe(self):
        return {"origin": [round(x, 6) for x in self.origin],
                "U": [round(x, 9) for x in self.U],
                "V": [round(x, 9) for x in self.V],
                "Z": [round(x, 9) for x in self.Z]}


def _cross(a, b):
    return tuple(_session_cross(a, b))


def _unit(a):
    return tuple(_session_unit(a, zero="raise"))


def normalize(a):
    return _unit([float(x) for x in a])


def dot(a, b):
    return _dot([float(x) for x in a], [float(x) for x in b])


def cross(a, b):
    return _cross([float(x) for x in a], [float(x) for x in b])


def offset(p, vec, t):
    return NXOpen.Point3d(p.X + t * vec[0], p.Y + t * vec[1],
                          p.Z + t * vec[2])


def perpendicular(axis, hint=None):
    """与 axis 垂直的单位向量；hint 给定时用 hint 正交化，否则取稳定轴。"""
    a = _unit(axis)
    if hint is not None:
        h = _unit(hint)
        c = _cross(a, h)
        if math.sqrt(_dot(c, c)) > 1e-6:
            return _unit(c)
    ref = (0.0, 0.0, 1.0) if abs(a[2]) < 0.9 else (1.0, 0.0, 0.0)
    return _unit(_cross(a, ref))


# ------------------------------------------------------------------ curves

def line(wp, a, b):
    return wp.Curves.CreateLine(a, b)


def arc(wp, c, xdir, ydir, r, a0, a1):
    """圆弧：中心 c、平面基 xdir/ydir、半径 r（数字）、起止角（弧度）。"""
    return wp.Curves.CreateArc(c, xdir, ydir, float(r), float(a0), float(a1))


def polyline(wp, pts, close=True):
    cs = [line(wp, pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if close:
        cs.append(line(wp, pts[-1], pts[0]))
    return cs


def loop_uv(wp, frame, pts_uv, z=0.0):
    """(u,v) 平面闭合折线（data 层轮廓）。"""
    ps = [frame.pt(u, v, z) for (u, v) in pts_uv]
    return polyline(wp, ps)


def loop_uz(wp, frame, pts_uz, v=0.0):
    """(u,z) 平面闭合折线（侧视轮廓）。"""
    ps = [frame.pt(u, v, z) for (u, z) in pts_uz]
    return polyline(wp, ps)


def loop_vz(wp, frame, pts_vz, u=0.0):
    """(v,z) 平面闭合折线（端视轮廓）。"""
    ps = [frame.pt(u, v, z) for (v, z) in pts_vz]
    return polyline(wp, ps)


# ------------------------------------------------------------------ datum

def _xyz(p):
    """Point3d / Point / (x,y,z) 统一成三元组。"""
    if hasattr(p, "X"):
        return (float(p.X), float(p.Y), float(p.Z))
    return (float(p[0]), float(p[1]), float(p[2]))


def axis(wp, p, direction):
    """基准轴（SmartObject，不是特征）：位置/方向按 data 层字面值。"""
    d = _unit(direction)
    q = _xyz(p)
    return wp.Axes.CreateAxis(
        NXOpen.Point3d(q[0], q[1], q[2]),
        NXOpen.Vector3d(d[0], d[1], d[2]),
        NXOpen.SmartObject.UpdateOption.WithinModeling)


def plane(wp, p, normal):
    """固定平面（SmartObject）：位置/法向按 data 层字面值。"""
    d = _unit(normal)
    q = _xyz(p)
    return wp.Planes.CreatePlane(
        NXOpen.Point3d(q[0], q[1], q[2]),
        NXOpen.Vector3d(d[0], d[1], d[2]),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
