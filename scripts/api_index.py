# -*- coding: utf-8 -*-
"""NXOpen 离线索引：pyi / 运行期反射 / hxx 三源对比。

数据不进仓库（pyi 快照无 LICENSE，头文件属 NX 安装目录）。本工具只读
调用方给的路径，输出 JSON 或摘要：

  - 类集合：common / pyi_only / runtime_only（按 `模块.类` 全名）；
  - 公开成员缺失：pyi 有、运行期没有（只算非下划线名）；
  - hxx 索引：`class [NX_DEPRECATED(...)] EXPORT Name` 全收，修掉旧正则
    漏收 72 个 deprecated 类的问题；
  - 签名：pyi 的 `def` 参数表与运行期签名 JSON 对比，统计可逐参数校验
    的比例；运行期拿不到参数名时只报 arity。

用法：
    python scripts/api_index.py --pyi <dir> --runtime <json> \\
        [--headers <NX UGOPEN/NXOpen>] [--signatures <json>] [--json out]
"""
import argparse
import ast
import json
import os
import re
import sys


def _walk_classes(node, prefix, out):
    for child in node.body:
        if not isinstance(child, ast.ClassDef):
            continue
        name = prefix + child.name
        members = set()
        methods = {}
        for item in child.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.add(item.name)
                args = [a.arg for a in item.args.args if a.arg != "self"]
                args += [a.arg for a in item.args.kwonlyargs]
                # 同名 def 是 overload：保留全部参数表，不能只留最后一个。
                methods.setdefault(item.name, []).append(args)
            elif isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name):
                members.add(item.target.id)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        members.add(t.id)
        bases = []
        for b in child.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(b.attr)
        out[name] = {"members": members, "methods": methods, "bases": bases}
        _walk_classes(child, name + ".", out)


def pyi_classes(path):
    out, err = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except SyntaxError as exc:
        return out, "SYNTAX:%s" % exc
    _walk_classes(tree, "", out)
    return out, err


def load_pyi(root):
    classes = {}
    files = 0
    errors = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".pyi"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            mod = rel[:-4].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            found, err = pyi_classes(full)
            files += 1
            if err:
                errors.append((mod, err))
            for cls, info in found.items():
                classes[mod + "." + cls] = info
    return {"files": files, "classes": classes, "errors": errors}


def load_runtime(path):
    with open(path, encoding="utf-8") as fh:
        inv = json.load(fh)
    out = {}
    for mod, classes in inv.get("modules", {}).items():
        for cls, members in classes.items():
            out[mod + "." + cls] = set(members)
    return out


_DEPRECATED = (r'NX_DEPRECATED\s*\(\s*"(?:[^"\\]|\\.)*"\s*\)\s+')
_HXX_CLASS = re.compile(
    r"(?m)^\s*(?:template\s*<[^>]*>\s*)?class\s+"
    r"(?:" + _DEPRECATED + r")?"
    r"(?:[A-Z0-9_]+EXPORT\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)")
_HXX_DEPRECATED = re.compile(
    r"(?m)^\s*class\s+" + _DEPRECATED +
    r"(?:[A-Z0-9_]+EXPORT\s+)?([A-Za-z_][A-Za-z0-9_]*)")


def load_headers(root):
    classes = {}
    deprecated = []
    files = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith((".hxx", ".h")):
                continue
            full = os.path.join(dirpath, name)
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            files += 1
            for m in _HXX_CLASS.finditer(text):
                classes.setdefault(m.group(1), 0)
                classes[m.group(1)] += 1
            for m in _HXX_DEPRECATED.finditer(text):
                deprecated.append(m.group(1))
    return {"files": files, "classes": set(classes),
            "deprecated": sorted(set(deprecated))}


def compare(pyi, runtime):
    common = set(pyi) & set(runtime)
    missing_total = 0
    missing_public = 0
    compared = 0
    for cls in common:
        missing = pyi[cls]["members"] - runtime[cls]
        compared += len(pyi[cls]["members"])
        missing_total += len(missing)
        missing_public += len([m for m in missing if not m.startswith("_")])
    return {
        "pyi_classes": len(pyi),
        "runtime_classes": len(runtime),
        "common": len(common),
        "pyi_only": len(set(pyi) - set(runtime)),
        "runtime_only": len(set(runtime) - set(pyi)),
        "members_compared": compared,
        "members_absent": missing_total,
        "public_absent": missing_public,
        "runtime_only_sample": sorted(set(runtime) - set(pyi))[:12],
    }


def enum_artifacts(runtime):
    return [c for c in runtime if c.rsplit(".", 1)[-1].endswith("MemberType")]


def signature_check(pyi, sig_path):
    """运行期签名 JSON：[{class, member, args|arity, ok}]；返回覆盖率。"""
    with open(sig_path, encoding="utf-8") as fh:
        rows = json.load(fh)
    stats = {"rows": len(rows), "have_args": 0, "have_arity": 0,
             "no_signature": 0, "matched": 0, "mismatched": []}
    for row in rows:
        cls = row.get("class")
        member = row.get("member")
        if row.get("signature_ok") and row.get("args") is not None:
            stats["have_args"] += 1
            want = method_overloads(pyi, cls, member)
            if want is not None:
                got = [a for a in row["args"] if a != "self"]
                if got in want:
                    stats["matched"] += 1
                else:
                    stats["mismatched"].append(
                        (cls, member, want, row["args"]))
        elif row.get("arity") is not None:
            stats["have_arity"] += 1
        else:
            stats["no_signature"] += 1
    return stats


def _find_class(pyi, name):
    if name in pyi:
        return name
    suffix = "." + name
    for key in pyi:
        if key.endswith(suffix):
            return key
    return None


def method_overloads(pyi, cls, member, seen=None):
    """按 pyi 的 bases 递归找成员；返回参数表列表或 None。"""
    key = _find_class(pyi, cls)
    if key is None:
        return None
    info = pyi[key]
    if member in info["methods"]:
        return info["methods"][member]
    seen = seen or set()
    if key in seen:
        return None
    seen.add(key)
    for base in info["bases"]:
        got = method_overloads(pyi, base, member, seen)
        if got is not None:
            return got
    return None


def load_doc_jsonl(path):
    """读 NX 运行期采集的 JSONL：dotted + members.<name>.doc.sigs。

    每行一个类；`sigs` 是 [[方法名, [参数名...]], ...]（property 为 None）。
    返回 {(class, member): [参数表, ...]}。
    """
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cls = rec.get("dotted") or rec.get("class")
            for name, info in rec.get("members", {}).items():
                sigs = (info.get("doc") or {}).get("sigs") or []
                params = []
                for sig in sigs:
                    if (isinstance(sig, (list, tuple)) and len(sig) > 1
                            and sig[1] is not None):
                        params.append([a for a in sig[1] if a != "self"])
                out[(cls, name)] = params
    return out


def doc_signature_check(pyi, doc):
    """运行期 __doc__ 的 Signature 块 vs pyi 全 overload。"""
    stats = {"members": 0, "exact": 0, "arity_only": 0,
             "order_or_name_diff": 0, "no_signature": 0, "unknown": 0}
    for (cls, name), sigs in doc.items():
        want = method_overloads(pyi, cls, name)
        if want is None:
            stats["unknown"] += 1
            continue
        stats["members"] += 1
        if not sigs:
            stats["no_signature"] += 1
        elif any(s in want for s in sigs):
            stats["exact"] += 1
        elif any(len(s) == len(w) for s in sigs for w in want):
            stats["arity_only"] += 1
        else:
            stats["order_or_name_diff"] += 1
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pyi")
    ap.add_argument("--runtime")
    ap.add_argument("--headers")
    ap.add_argument("--signatures")
    ap.add_argument("--doc-jsonl")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if not (args.pyi and args.runtime):
        raise SystemExit("need --pyi and --runtime")
    pyi = load_pyi(args.pyi)
    runtime = load_runtime(args.runtime)
    summary = compare(pyi["classes"], runtime)
    summary["pyi_files"] = pyi["files"]
    summary["pyi_syntax_errors"] = len(pyi["errors"])
    summary["runtime_enum_artifacts"] = len(enum_artifacts(runtime))
    print("pyi_files=%(pyi_files)d pyi_classes=%(pyi_classes)d "
          "runtime_classes=%(runtime_classes)d common=%(common)d "
          "pyi_only=%(pyi_only)d runtime_only=%(runtime_only)d" % summary)
    print("members_compared=%(members_compared)d absent=%(members_absent)d "
          "public_absent=%(public_absent)d" % summary)
    print("runtime_enum_artifacts=%(runtime_enum_artifacts)d" % summary)
    if args.headers:
        hxx = load_headers(args.headers)
        known = set(c.rsplit(".", 1)[-1] for c in runtime)
        summary["hxx_files"] = hxx["files"]
        summary["hxx_classes"] = len(hxx["classes"])
        summary["hxx_deprecated"] = len(hxx["deprecated"])
        summary["hxx_deprecated_in_runtime"] = len(
            [c for c in hxx["deprecated"] if c in known])
        print("hxx_files=%(hxx_files)d hxx_classes=%(hxx_classes)d "
              "deprecated=%(hxx_deprecated)d "
              "deprecated_in_runtime=%(hxx_deprecated_in_runtime)d"
              % summary)
    if args.signatures:
        sig = signature_check(pyi["classes"], args.signatures)
        summary["signatures"] = sig
        print("signature_rows=%d have_args=%d have_arity=%d no_signature=%d "
              "matched=%d mismatched=%d"
              % (sig["rows"], sig["have_args"], sig["have_arity"],
                 sig["no_signature"], sig["matched"],
                 len(sig["mismatched"])))
    if args.doc_jsonl:
        doc = load_doc_jsonl(args.doc_jsonl)
        sig = doc_signature_check(pyi["classes"], doc)
        summary["doc_signatures"] = sig
        print("doc_members=%(members)d exact=%(exact)d "
              "arity_only=%(arity_only)d diff=%(order_or_name_diff)d "
              "no_signature=%(no_signature)d unknown=%(unknown)d" % sig)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
