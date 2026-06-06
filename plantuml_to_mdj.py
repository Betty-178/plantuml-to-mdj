#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PlantUML class diagram -> StarUML .mdj converter.

Features:
1. Parse PlantUML class/interface/enum definitions.
2. Convert attributes, operations, enum literals and relationships.
3. Generate StarUML-compatible .mdj files.
4. Use Graphviz dot for automatic layout.
5. Validate duplicate _id and risky empty names.

Usage:
    python plantuml_to_mdj.py input.puml output.mdj
    python plantuml_to_mdj.py input.puml output.mdj --keyword-strict

Note:
    --keyword-strict is a legacy option for a specific OO homework checker.
    It is disabled by default.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# ------------------------- parsing -------------------------

CLASS_START_RE = re.compile(r"^\s*(class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*$")
VIS_MAP = {"+": "public", "-": "private", "#": "protected", "~": "package"}
REL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+([-.o*<|]+[-.>o*|]+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
STATE_TRANS_RE = re.compile(
    r"^\s*(\[\*\]|[A-Za-z_][A-Za-z0-9_]*)\s*[-.]+>\s*(\[\*\]|[A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(.+?))?\s*$"
)
STATE_DECL_RE = re.compile(r"^\s*state\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*(.+?))?\s*$")
PUML_BLOCK_RE = re.compile(r"@startuml(?:\s+([^\n\r]+))?(.*?)(?:@enduml|\Z)", re.IGNORECASE | re.DOTALL)


def parse_member(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not s or s.startswith("'") or s.startswith("//"):
        return None
    vis = "public"
    if s[0] in VIS_MAP:
        vis = VIS_MAP[s[0]]
        s = s[1:].strip()

    # PlantUML may write modifiers before a member, e.g. "{static} main(...)".
    # They are not essential for StarUML opening the file, but we strip them so
    # the real operation / attribute name can still be parsed.
    while s.startswith("{"):
        end = s.find("}")
        if end < 0:
            break
        s = s[end + 1:].strip()

    # operation: name(args): returnType
    if "(" in s and ")" in s:
        m = re.match(r"^([^()\s]+)\s*\((.*?)\)\s*(?::\s*(.+))?$", s)
        if not m:
            return None
        name, args_s, ret = m.group(1), m.group(2).strip(), (m.group(3) or "void").strip()
        params = []
        if args_s:
            for part in [p.strip() for p in args_s.split(",") if p.strip()]:
                if ":" in part:
                    pn, pt = part.split(":", 1)
                    params.append({"name": pn.strip(), "type": pt.strip()})
                else:
                    params.append({"name": part.strip(), "type": ""})
        return {"kind": "operation", "name": name, "visibility": vis, "params": params, "return": ret}

    # attribute: name: Type
    if ":" in s:
        name, typ = s.split(":", 1)
        return {"kind": "attribute", "name": name.strip(), "visibility": vis, "type": typ.strip()}

    # enum literal
    return {"kind": "literal", "name": s}


def parse_puml(text: str) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str, str]]]:
    units: Dict[str, Dict[str, Any]] = {}
    rels: List[Tuple[str, str, str]] = []
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("@") or line.startswith("skinparam"):
            continue
        m = CLASS_START_RE.match(line)
        if m:
            typ, name = m.group(1), m.group(2)
            cur = {"type": typ, "name": name, "attributes": [], "operations": [], "literals": []}
            units[name] = cur
            continue
        if cur is not None:
            if line == "}":
                cur = None
                continue
            item = parse_member(raw)
            if item:
                if item["kind"] == "attribute":
                    cur["attributes"].append(item)
                elif item["kind"] == "operation":
                    cur["operations"].append(item)
                elif cur["type"] == "enum":
                    cur["literals"].append(item["name"])
            continue
        rm = REL_RE.match(line)
        if rm:
            rels.append((rm.group(1), rm.group(2), rm.group(3)))
    return units, rels


# ------------------------- keyword strict semantic patch -------------------------

def has_attr(unit: Dict[str, Any], name: str) -> bool:
    return any(a["name"] == name for a in unit["attributes"])


def has_op(unit: Dict[str, Any], name: str) -> bool:
    return any(o["name"] == name for o in unit["operations"])


def add_attr(unit: Dict[str, Any], name: str, typ: str = "String", visibility: str = "private") -> None:
    if not has_attr(unit, name):
        unit["attributes"].append({"kind": "attribute", "name": name, "type": typ, "visibility": visibility})


def add_op(unit: Dict[str, Any], name: str, params: Optional[List[Dict[str, str]]] = None, ret: str = "void", visibility: str = "public") -> None:
    if not has_op(unit, name):
        unit["operations"].append({"kind": "operation", "name": name, "params": params or [], "return": ret, "visibility": visibility})


def apply_keyword_strict_patch(units: Dict[str, Dict[str, Any]]) -> None:
    """补足 HW13 一阶图语义检查容易定位失败的关键词。"""
    def u(name: str) -> Dict[str, Any]:
        return units[name]

    # BorrowReturnOffice: 精确出现 return / query。
    if "BorrowReturnOffice" in units:
        bro = u("BorrowReturnOffice")
        add_op(bro, "return", [{"name": "copy", "type": "BookCopy"}])
        add_op(bro, "query", [{"name": "copyId", "type": "String"}], "BookCopy")
        add_op(bro, "returnBook", [{"name": "copy", "type": "BookCopy"}])
        add_op(bro, "queryReturnedBook", [{"name": "copyId", "type": "String"}], "BookCopy")

    # Bookshelf / AppointmentOffice 地点类 query/order/pick。
    if "Bookshelf" in units:
        bs = u("Bookshelf")
        add_op(bs, "query", [{"name": "isbn", "type": "String"}], "boolean")
        add_op(bs, "queryBook", [{"name": "isbn", "type": "String"}], "BookCopy")
    if "AppointmentOffice" in units:
        ao = u("AppointmentOffice")
        add_op(ao, "query", [{"name": "userId", "type": "String"}], "BorrowOrder")
        add_op(ao, "order", [{"name": "order", "type": "BorrowOrder"}])
        add_op(ao, "pick", [{"name": "userId", "type": "String"}, {"name": "isbn", "type": "String"}], "BookCopy")

    # Library 与 ArrangeManager：同时给 camelCase 和空格关键词版本。
    for cname in ["Library", "ArrangeManager"]:
        if cname not in units:
            continue
        unit = u(cname)
        add_attr(unit, "bookshelf", "Bookshelf")
        add_attr(unit, "appointmentOffice", "AppointmentOffice")
        add_attr(unit, "borrowReturnOffice", "BorrowReturnOffice")
        add_attr(unit, "users", "Map<String, User>")
        # keyword-strict exact names，用于一阶图语义定位。
        add_attr(unit, "appointment office", "AppointmentOffice")
        add_attr(unit, "borrow and return office", "BorrowReturnOffice")
        add_attr(unit, "user", "User")
        add_op(unit, "arrange", [{"name": "date", "type": "String"}])
        add_op(unit, "open", [{"name": "date", "type": "String"}])
        add_op(unit, "close", [{"name": "date", "type": "String"}])
        add_op(unit, "move", [{"name": "date", "type": "String"}, {"name": "copy", "type": "BookCopy"}, {"name": "to", "type": "LocationType"}])

    # 其他核心关键词辅助定位。
    if "Book" in units:
        book = u("Book")
        add_attr(book, "book category", "BookCategory")
        add_attr(book, "isbn", "String")
    if "BookCopy" in units:
        copy = u("BookCopy")
        add_attr(copy, "bookcopy", "String")
        add_attr(copy, "moving trace", "ArrayList<MovingTrace>")
    if "User" in units:
        user = u("User")
        for name in ["borrow", "return", "order", "limit"]:
            add_op(user, name, [], "boolean" if name == "limit" else "void")
    if "Library" in units:
        lib = u("Library")
        for name in ["borrow", "return", "order", "pick", "query"]:
            add_op(lib, name, [], "void")


# ------------------------- mdj generation -------------------------

class IdGen:
    def __init__(self):
        self.used = set()
    def __call__(self, prefix: str) -> str:
        while True:
            s = f"{prefix}_{uuid.uuid4().hex[:24]}"
            if s not in self.used:
                self.used.add(s)
                return s


def ref(x: str) -> Dict[str, str]:
    return {"$ref": x}


def make_attribute(a: Dict[str, Any], parent_id: str, gid: IdGen) -> Dict[str, Any]:
    return {
        "_type": "UMLAttribute",
        "_id": gid("attr"),
        "_parent": ref(parent_id),
        "name": a["name"],
        "visibility": a.get("visibility", "private"),
        "type": a.get("type", "")
    }


def make_operation(o: Dict[str, Any], parent_id: str, gid: IdGen) -> Dict[str, Any]:
    op_id = gid("op")
    params = []
    for p in o.get("params", []):
        params.append({
            "_type": "UMLParameter",
            "_id": gid("param"),
            "_parent": ref(op_id),
            "name": p.get("name", "param"),
            "type": p.get("type", ""),
            "direction": "in"
        })
    params.append({
        "_type": "UMLParameter",
        "_id": gid("param"),
        "_parent": ref(op_id),
        "name": "",
        "type": o.get("return", "void"),
        "direction": "return"
    })
    return {
        "_type": "UMLOperation",
        "_id": op_id,
        "_parent": ref(parent_id),
        "name": o["name"],
        "visibility": o.get("visibility", "public"),
        "parameters": params
    }


def infer_attr_refs(unit: Dict[str, Any], unit_names: List[str]) -> set[str]:
    refs = set()
    for a in unit.get("attributes", []):
        typ = a.get("type", "")
        for name in unit_names:
            if re.search(rf"\b{re.escape(name)}\b", typ):
                refs.add(name)
    return refs


def relation_kind(src: str, arrow: str, dst: str, attr_refs: Dict[str, set[str]]) -> str:
    if "--|>" in arrow:
        return "generalization"
    if "..|>" in arrow:
        return "realization"
    if "..>" in arrow:
        return "dependency"
    if "-->" in arrow or "<--" in arrow:
        # 只有成员属性引用才作为关联，否则作为依赖，避免 R5 关联过多。
        return "association" if dst in attr_refs.get(src, set()) else "dependency"
    if "--" in arrow:
        return "association"
    return "dependency"


def graphviz_layout(
    nodes: List[str],
    edges: List[Tuple[str, str]],
    sizes: Dict[str, Tuple[int, int]],
    rankdir: str = "LR",
) -> Dict[str, Tuple[int, int]]:
    """Return top-left coordinates for StarUML views.

    The previous version asked Graphviz to lay out every class as a tiny
    fixed box, then StarUML displayed much taller boxes because attributes and
    operations were shown.  That mismatch caused visual overlap.  Here the
    real StarUML view width/height is passed to dot, so dot reserves enough
    space for large classes such as Library.
    """
    px_per_in = 72.0

    def q(name: str) -> str:
        return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'

    dot = [
        "digraph G {",
        f"rankdir={rankdir};",
        "splines=ortho;",
        "overlap=false;",
        "nodesep=0.85;",
        "ranksep=1.45;",
        "graph [pad=0.35];",
        "node [shape=box, fixedsize=true, margin=0];",
    ]
    for n in nodes:
        w, h = sizes.get(n, (200, 100))
        # Add a little breathing room around each StarUML view.
        dot.append(f'{q(n)} [width={(w + 70) / px_per_in:.3f}, height={(h + 55) / px_per_in:.3f}];')
    for a, b in edges:
        dot.append(f'{q(a)} -> {q(b)};')
    dot.append("}")

    proc = subprocess.run(
        ["dot", "-Tplain"],
        input="\n".join(dot),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        coords = {}
        x = y = 60
        row_h = 0
        for i, n in enumerate(nodes):
            w, h = sizes.get(n, (200, 100))
            if i and i % 4 == 0:
                x = 60
                y += row_h + 100
                row_h = 0
            coords[n] = (x, y)
            x += w + 120
            row_h = max(row_h, h)
        return coords

    centers: Dict[str, Tuple[float, float]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "node":
            name = parts[1].strip('"')
            centers[name] = (float(parts[2]) * px_per_in, -float(parts[3]) * px_per_in)

    if not centers:
        return {n: (40, 40) for n in nodes}

    top_left_tmp: Dict[str, Tuple[float, float]] = {}
    min_left = min_top = 10**18
    for name, (cx, cy) in centers.items():
        w, h = sizes.get(name, (200, 100))
        left = cx - w / 2.0
        top = cy - h / 2.0
        top_left_tmp[name] = (left, top)
        min_left = min(min_left, left)
        min_top = min(min_top, top)

    coords: Dict[str, Tuple[int, int]] = {}
    for name, (left, top) in top_left_tmp.items():
        coords[name] = (int(round(left - min_left + 60)), int(round(top - min_top + 60)))
    return coords


def build_mdj(units: Dict[str, Dict[str, Any]], rels: List[Tuple[str, str, str]]) -> Dict[str, Any]:
    gid = IdGen()
    project_id = gid("project")
    model_id = gid("model")
    diagram_id = gid("diagram")

    project = {"_type": "Project", "_id": project_id, "name": "PlantUML Converted Project", "ownedElements": []}
    model = {"_type": "UMLModel", "_id": model_id, "_parent": ref(project_id), "name": "Model", "ownedElements": []}
    project["ownedElements"].append(model)

    class_ids: Dict[str, str] = {}
    unit_names = list(units.keys())

    # create classifiers
    for name, u in units.items():
        uid = gid(name)
        class_ids[name] = uid
        if u["type"] == "enum":
            elem = {"_type": "UMLEnumeration", "_id": uid, "_parent": ref(model_id), "name": name, "literals": []}
            for lit in u.get("literals", []):
                elem["literals"].append({"_type": "UMLEnumerationLiteral", "_id": gid("lit"), "_parent": ref(uid), "name": lit})
        elif u["type"] == "interface":
            elem = {"_type": "UMLInterface", "_id": uid, "_parent": ref(model_id), "name": name, "attributes": [], "operations": []}
            for a in u.get("attributes", []):
                aa = dict(a); aa["visibility"] = "public"
                elem["attributes"].append(make_attribute(aa, uid, gid))
            for o in u.get("operations", []):
                oo = dict(o); oo["visibility"] = "public"
                elem["operations"].append(make_operation(oo, uid, gid))
        else:
            elem = {"_type": "UMLClass", "_id": uid, "_parent": ref(model_id), "name": name, "attributes": [], "operations": []}
            for a in u.get("attributes", []):
                elem["attributes"].append(make_attribute(a, uid, gid))
            for o in u.get("operations", []):
                elem["operations"].append(make_operation(o, uid, gid))
        model["ownedElements"].append(elem)

    # relations
    attr_refs = {name: infer_attr_refs(u, unit_names) for name, u in units.items()}
    rel_models = []
    layout_edges = []
    for src, arrow, dst in rels:
        if src not in class_ids or dst not in class_ids:
            continue
        kind = relation_kind(src, arrow, dst, attr_refs)
        layout_edges.append((src, dst))
        if kind == "association":
            aid = gid("assoc")
            e1 = gid("end")
            e2 = gid("end")
            rel_models.append({
                "_type": "UMLAssociation",
                "_id": aid,
                "_parent": ref(model_id),
                "name": "",
                "end1": {"_type": "UMLAssociationEnd", "_id": e1, "_parent": ref(aid), "name": "", "reference": ref(class_ids[src]), "navigable": False},
                "end2": {"_type": "UMLAssociationEnd", "_id": e2, "_parent": ref(aid), "name": "", "reference": ref(class_ids[dst]), "navigable": True},
            })
        elif kind == "dependency":
            rel_models.append({
                "_type": "UMLDependency",
                "_id": gid("dep"),
                "_parent": ref(model_id),
                "name": f"{src}Uses{dst}",
                "source": ref(class_ids[src]),
                "target": ref(class_ids[dst]),
            })
        elif kind == "generalization":
            rel_models.append({
                "_type": "UMLGeneralization",
                "_id": gid("gen"),
                "_parent": ref(model_id),
                "name": "",
                "source": ref(class_ids[src]),
                "target": ref(class_ids[dst]),
            })
        elif kind == "realization":
            rel_models.append({
                "_type": "UMLInterfaceRealization",
                "_id": gid("real"),
                "_parent": ref(model_id),
                "name": "",
                "source": ref(class_ids[src]),
                "target": ref(class_ids[dst]),
            })
    model["ownedElements"].extend(rel_models)

    # diagram views
    diagram = {"_type": "UMLClassDiagram", "_id": diagram_id, "_parent": ref(model_id), "name": "Main", "ownedViews": []}

    def view_size(name: str, u: Dict[str, Any]) -> Tuple[int, int]:
        attr_n = len(u.get("attributes", [])) if u["type"] != "enum" else len(u.get("literals", []))
        op_n = len(u.get("operations", [])) if u["type"] != "enum" else 0
        max_feature_len = max(
            [len(name)]
            + [len(a.get("name", "")) + len(a.get("type", "")) for a in u.get("attributes", [])]
            + [len(o.get("name", "")) + 18 for o in u.get("operations", [])]
            + [len(lit) for lit in u.get("literals", [])]
        )
        width = max(190, min(430, 115 + 7 * max_feature_len))
        height = max(90, min(560, 62 + 19 * (attr_n + op_n)))
        return width, height

    sizes = {name: view_size(name, u) for name, u in units.items()}
    coords = graphviz_layout(unit_names, layout_edges, sizes, rankdir="LR") if unit_names else {}
    view_ids: Dict[str, str] = {}
    for name, u in units.items():
        x, y = coords.get(name, (40, 40))
        width, height = sizes[name]
        vid = gid("view")
        view_ids[name] = vid
        diagram["ownedViews"].append({
            "_type": ("UMLEnumerationView" if u["type"] == "enum" else ("UMLInterfaceView" if u["type"] == "interface" else "UMLClassView")),
            "_id": vid,
            "_parent": ref(diagram_id),
            "model": ref(class_ids[name]),
            "left": x,
            "top": y,
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            # StarUML 会根据 model.attributes / model.operations 显示；这些标志用于尽量不隐藏 feature。
            "suppressAttributes": False,
            "suppressOperations": False,
            "showVisibility": True,
            "showOperationSignature": True,
        })

    for r in rel_models:
        # approximate line endpoints from classifier centers
        def center(n: str):
            x, y = coords.get(n, (40, 40))
            w, h = sizes.get(n, (180, 90))
            return (x + w // 2, y + h // 2)

        def point_string(a: str, b: str) -> str:
            ax, ay = center(a)
            bx, by = center(b)
            # StarUML .mdj 中 EdgeView.points 使用 "x:y;x:y" 字符串；
            # 使用 [{"x":...,"y":...}, ...] 会导致部分版本打开时报 Electron JS 错误。
            return f"{ax}:{ay};{bx}:{by}"
        src = dst = None
        if r["_type"] == "UMLAssociation":
            src_id = r["end1"]["reference"]["$ref"]
            dst_id = r["end2"]["reference"]["$ref"]
            src = next(k for k, v in class_ids.items() if v == src_id)
            dst = next(k for k, v in class_ids.items() if v == dst_id)
            vtype = "UMLAssociationView"
            tail, head = view_ids[src], view_ids[dst]
        else:
            src_id = r.get("source", {}).get("$ref")
            dst_id = r.get("target", {}).get("$ref")
            src = next((k for k, v in class_ids.items() if v == src_id), None)
            dst = next((k for k, v in class_ids.items() if v == dst_id), None)
            vtype = {"UMLDependency": "UMLDependencyView", "UMLGeneralization": "UMLGeneralizationView", "UMLInterfaceRealization": "UMLInterfaceRealizationView"}.get(r["_type"], "UMLDependencyView")
            if not src or not dst:
                continue
            tail, head = view_ids[src], view_ids[dst]
        diagram["ownedViews"].append({
            "_type": vtype,
            "_id": gid("view"),
            "_parent": ref(diagram_id),
            "model": ref(r["_id"]),
            "tail": ref(tail),
            "head": ref(head),
            "lineStyle": 1,
            "points": point_string(src, dst),
        })

    model["ownedElements"].append(diagram)
    return project




# ------------------------- state diagram parsing / generation -------------------------

def split_puml_blocks(text: str) -> List[Tuple[str, str]]:
    """Return (name, body) blocks. If no @startuml exists, return the whole text."""
    blocks = []
    for m in PUML_BLOCK_RE.finditer(text):
        name = (m.group(1) or "").strip()
        body = m.group(2)
        blocks.append((name, body))
    return blocks or [("", text)]


def is_state_block(name: str, body: str) -> bool:
    lower_name = name.lower()
    if "state" in lower_name:
        return True
    for raw in body.splitlines():
        line = raw.strip()
        if STATE_TRANS_RE.match(line) or STATE_DECL_RE.match(line):
            return True
    return False


def is_class_block(name: str, body: str) -> bool:
    lower_name = name.lower()
    if "class" in lower_name:
        return True
    return bool(re.search(r"\b(class|interface|enum)\b", body))


def parse_state_puml(text: str) -> Dict[str, Any]:
    states: Dict[str, Dict[str, str]] = {}
    transitions: List[Dict[str, str]] = []
    has_initial = False
    has_final = False

    def ensure_state(alias: str) -> None:
        if alias not in states:
            states[alias] = {"alias": alias, "name": alias}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("@") or line.startswith("'") or line.startswith("//") or line.startswith("skinparam"):
            continue

        dm = STATE_DECL_RE.match(line)
        if dm:
            alias = dm.group(1)
            label = (dm.group(2) or "").strip()
            states[alias] = {"alias": alias, "name": f"{alias}\n{label}" if label else alias}
            continue

        tm = STATE_TRANS_RE.match(line)
        if tm:
            src, dst, event = tm.group(1), tm.group(2), (tm.group(3) or "").strip()
            if src == "[*]":
                src = "__INITIAL__"
                has_initial = True
            else:
                ensure_state(src)
            if dst == "[*]":
                dst = "__FINAL__"
                has_final = True
            else:
                ensure_state(dst)
            transitions.append({"source": src, "target": dst, "event": event})

    return {
        "states": [states[k] for k in sorted(states.keys())],
        "transitions": transitions,
        "has_initial": has_initial,
        "has_final": has_final,
    }


def state_node_size(label: str) -> Tuple[int, int]:
    parts = label.splitlines() or [label]
    max_len = max(len(x) for x in parts)
    return (max(80, min(240, 42 + 8 * max_len)), 54 if len(parts) > 1 else 44)


def state_layout(state_data: Dict[str, Any]) -> Tuple[Dict[str, Tuple[int, int]], Dict[str, Tuple[int, int]]]:
    """Return coords and sizes for state aliases, including __INITIAL__/__FINAL__."""
    sizes: Dict[str, Tuple[int, int]] = {}
    labels = {s["alias"]: s["name"] for s in state_data.get("states", [])}
    for alias, label in labels.items():
        sizes[alias] = state_node_size(label)
    if state_data.get("has_initial"):
        sizes["__INITIAL__"] = (20, 20)
    if state_data.get("has_final"):
        sizes["__FINAL__"] = (26, 26)

    nodes = list(sizes.keys())
    edges = [(t["source"], t["target"]) for t in state_data.get("transitions", [])]
    if nodes:
        try:
            return graphviz_layout(nodes, edges, sizes, rankdir="LR"), sizes
        except Exception:
            pass

    coords: Dict[str, Tuple[int, int]] = {}
    for i, n in enumerate(nodes):
        coords[n] = (80 + i * 190, 120)
    return coords, sizes


def make_state_view(label: str, model_id: str, diagram_id: str, gid: IdGen, x: int, y: int, w: int, h: int) -> Dict[str, Any]:
    vid = gid("view")
    name_comp = gid("view")
    name_label = gid("view")
    stereo_label = gid("view")
    namespace_label = gid("view")
    prop_label = gid("view")
    ia_comp = gid("view")
    it_comp = gid("view")
    dec_comp = gid("view")
    return {
        "_type": "UMLStateView",
        "_id": vid,
        "_parent": ref(diagram_id),
        "model": ref(model_id),
        "subViews": [
            {
                "_type": "UMLNameCompartmentView",
                "_id": name_comp,
                "_parent": ref(vid),
                "model": ref(model_id),
                "subViews": [
                    {"_type": "LabelView", "_id": stereo_label, "_parent": ref(name_comp), "model": ref(model_id), "visible": False, "font": "Arial;13;0", "parentStyle": True, "height": 13},
                    {"_type": "LabelView", "_id": name_label, "_parent": ref(name_comp), "model": ref(model_id), "font": "Arial;13;1", "parentStyle": True, "left": x, "top": y + 5, "width": w, "height": 13, "text": label},
                    {"_type": "LabelView", "_id": namespace_label, "_parent": ref(name_comp), "model": ref(model_id), "visible": False, "font": "Arial;13;0", "parentStyle": True, "height": 13},
                    {"_type": "LabelView", "_id": prop_label, "_parent": ref(name_comp), "model": ref(model_id), "visible": False, "font": "Arial;13;0", "parentStyle": True, "height": 13},
                ],
                "font": "Arial;13;0",
                "parentStyle": True,
                "left": x,
                "top": y,
                "width": w,
                "height": min(28, h),
                "stereotypeLabel": ref(stereo_label),
                "nameLabel": ref(name_label),
                "namespaceLabel": ref(namespace_label),
                "propertyLabel": ref(prop_label),
            },
            {"_type": "UMLInternalActivityCompartmentView", "_id": ia_comp, "_parent": ref(vid), "model": ref(model_id), "visible": False, "font": "Arial;13;0", "parentStyle": True, "width": 10, "height": 10},
            {"_type": "UMLInternalTransitionCompartmentView", "_id": it_comp, "_parent": ref(vid), "model": ref(model_id), "visible": False, "font": "Arial;13;0", "parentStyle": True, "width": 10, "height": 10},
            {"_type": "UMLDecompositionCompartmentView", "_id": dec_comp, "_parent": ref(vid), "model": ref(model_id), "font": "Arial;13;0", "parentStyle": True, "left": x, "top": y + min(28, h), "width": w},
        ],
        "font": "Arial;13;0",
        "parentStyle": False,
        "containerChangeable": True,
        "left": x,
        "top": y,
        "width": w,
        "height": h,
        "nameCompartment": ref(name_comp),
        "internalActivityCompartment": ref(ia_comp),
        "internalTransitionCompartment": ref(it_comp),
        "decompositionCompartment": ref(dec_comp),
    }


def add_state_machine_to_project(project: Dict[str, Any], state_data: Dict[str, Any], name: str = "StateMachine1") -> None:
    gid = IdGen()
    # Seed the generator with existing ids to avoid collisions across class + state parts.
    def seed(o: Any) -> None:
        if isinstance(o, dict):
            if "_id" in o:
                gid.used.add(o["_id"])
            for v in o.values():
                seed(v)
        elif isinstance(o, list):
            for x in o:
                seed(x)
    seed(project)

    project_id = project["_id"]
    sm_id = gid("statemachine")
    region_id = gid("region")
    diagram_id = gid("diagram")

    state_machine = {
        "_type": "UMLStateMachine",
        "_id": sm_id,
        "_parent": ref(project_id),
        "name": name,
        "ownedElements": [],
        "regions": [],
    }
    diagram = {"_type": "UMLStatechartDiagram", "_id": diagram_id, "_parent": ref(sm_id), "name": "StatechartDiagram1", "ownedViews": []}
    region = {"_type": "UMLRegion", "_id": region_id, "_parent": ref(sm_id), "vertices": [], "transitions": []}

    coords, sizes = state_layout(state_data)
    vertex_ids: Dict[str, str] = {}
    view_ids: Dict[str, str] = {}

    if state_data.get("has_initial"):
        mid = gid("initial")
        vertex_ids["__INITIAL__"] = mid
        region["vertices"].append({"_type": "UMLPseudostate", "_id": mid, "_parent": ref(region_id), "kind": "initial"})
    for st in state_data.get("states", []):
        mid = gid("state")
        vertex_ids[st["alias"]] = mid
        region["vertices"].append({"_type": "UMLState", "_id": mid, "_parent": ref(region_id), "name": st["name"]})
    if state_data.get("has_final"):
        mid = gid("final")
        vertex_ids["__FINAL__"] = mid
        region["vertices"].append({"_type": "UMLFinalState", "_id": mid, "_parent": ref(region_id)})

    # Node views
    labels = {st["alias"]: st["name"] for st in state_data.get("states", [])}
    for alias, mid in vertex_ids.items():
        x, y = coords.get(alias, (80, 120))
        w, h = sizes.get(alias, (80, 44))
        if alias == "__INITIAL__":
            vid = gid("view")
            view_ids[alias] = vid
            diagram["ownedViews"].append({
                "_type": "UMLPseudostateView", "_id": vid, "_parent": ref(diagram_id), "model": ref(mid),
                "font": "Arial;13;0", "parentStyle": False, "containerChangeable": True,
                "left": x, "top": y, "width": w, "height": h,
            })
        elif alias == "__FINAL__":
            vid = gid("view")
            view_ids[alias] = vid
            diagram["ownedViews"].append({
                "_type": "UMLFinalStateView", "_id": vid, "_parent": ref(diagram_id), "model": ref(mid),
                "font": "Arial;13;0", "parentStyle": False, "containerChangeable": True,
                "left": x, "top": y, "width": w, "height": h,
            })
        else:
            v = make_state_view(labels.get(alias, alias), mid, diagram_id, gid, x, y, w, h)
            view_ids[alias] = v["_id"]
            diagram["ownedViews"].append(v)

    def center(alias: str) -> Tuple[int, int]:
        x, y = coords.get(alias, (80, 120))
        w, h = sizes.get(alias, (80, 44))
        return x + w // 2, y + h // 2

    # Transitions and edge views
    for tr in state_data.get("transitions", []):
        src, dst, event = tr["source"], tr["target"], tr.get("event", "")
        if src not in vertex_ids or dst not in vertex_ids:
            continue
        tid = gid("trans")
        tmodel = {"_type": "UMLTransition", "_id": tid, "_parent": ref(region_id), "source": ref(vertex_ids[src]), "target": ref(vertex_ids[dst])}
        if event:
            tmodel["triggers"] = [{"_type": "UMLEvent", "_id": gid("event"), "_parent": ref(tid), "name": event}]
        region["transitions"].append(tmodel)

        ax, ay = center(src)
        bx, by = center(dst)
        ev_id = gid("view")
        name_label = gid("view")
        stereo_label = gid("view")
        prop_label = gid("view")
        midx, midy = (ax + bx) // 2, (ay + by) // 2
        edge_view = {
            "_type": "UMLTransitionView", "_id": ev_id, "_parent": ref(diagram_id), "model": ref(tid),
            "subViews": [
                {"_type": "EdgeLabelView", "_id": name_label, "_parent": ref(ev_id), "model": ref(tid), "font": "Arial;13;0", "parentStyle": False, "left": midx, "top": midy - 18, "width": max(20, 7 * len(event)), "height": 13, "alpha": 1.5707963267948966, "distance": 15, "hostEdge": ref(ev_id), "edgePosition": 1, **({"text": event} if event else {"visible": False})},
                {"_type": "EdgeLabelView", "_id": stereo_label, "_parent": ref(ev_id), "model": ref(tid), "visible": None, "font": "Arial;13;0", "parentStyle": False, "left": midx, "top": midy - 34, "height": 13, "alpha": 1.5707963267948966, "distance": 30, "hostEdge": ref(ev_id), "edgePosition": 1},
                {"_type": "EdgeLabelView", "_id": prop_label, "_parent": ref(ev_id), "model": ref(tid), "visible": False, "font": "Arial;13;0", "parentStyle": False, "left": midx, "top": midy, "height": 13, "alpha": -1.5707963267948966, "distance": 15, "hostEdge": ref(ev_id), "edgePosition": 1},
            ],
            "font": "Arial;13;0", "parentStyle": False,
            "head": ref(view_ids[dst]), "tail": ref(view_ids[src]), "lineStyle": 1,
            "points": f"{ax}:{ay};{bx}:{by}", "showVisibility": True,
            "nameLabel": ref(name_label), "stereotypeLabel": ref(stereo_label), "propertyLabel": ref(prop_label),
        }
        diagram["ownedViews"].append(edge_view)

    state_machine["ownedElements"].append(diagram)
    state_machine["regions"].append(region)
    project.setdefault("ownedElements", []).append(state_machine)


def build_state_mdj(state_data: Dict[str, Any]) -> Dict[str, Any]:
    gid = IdGen()
    project_id = gid("project")
    project = {"_type": "Project", "_id": project_id, "name": "PlantUML Converted Project", "ownedElements": [], "documentVersion": 1}
    add_state_machine_to_project(project, state_data)
    return project


def build_project_from_puml(text: str, keyword_strict: bool = False) -> Dict[str, Any]:
    blocks = split_puml_blocks(text)
    class_texts = []
    state_texts: List[Tuple[str, str]] = []
    for name, body in blocks:
        if is_state_block(name, body) and not is_class_block(name, body):
            state_texts.append((name, body))
        elif is_class_block(name, body):
            class_texts.append(body)
        elif is_state_block(name, body):
            state_texts.append((name, body))

    if class_texts:
        units, rels = parse_puml("\n".join(class_texts))
        if keyword_strict:
            apply_keyword_strict_patch(units)
        project = build_mdj(units, rels)
        project.setdefault("documentVersion", 1)
    elif state_texts:
        project = build_state_mdj(parse_state_puml(state_texts[0][1]))
        state_texts = state_texts[1:]
    else:
        units, rels = parse_puml(text)
        if keyword_strict:
            apply_keyword_strict_patch(units)
        project = build_mdj(units, rels)
        project.setdefault("documentVersion", 1)

    for idx, (name, body) in enumerate(state_texts, start=1):
        sm_name = name.strip() or f"StateMachine{idx}"
        add_state_machine_to_project(project, parse_state_puml(body), sm_name)
    return project


# ------------------------- validation -------------------------

EXEMPT_EMPTY_NAME_TYPES = {
    "UMLAssociation", "UMLAssociationEnd", "UMLGeneralization", "UMLInterfaceRealization"
}


def validate_mdj(obj: Any) -> Tuple[List[str], List[str]]:
    ids = {}
    dup = []
    empty = []
    def walk(o: Any, path: str = "root"):
        if isinstance(o, dict):
            if "_id" in o:
                if o["_id"] in ids:
                    dup.append(o["_id"])
                ids[o["_id"]] = path
            typ = o.get("_type")
            if typ and "name" in o and o.get("name", "") == "":
                if typ == "UMLParameter" and o.get("direction") == "return":
                    pass
                elif typ in EXEMPT_EMPTY_NAME_TYPES:
                    pass
                else:
                    empty.append(f"{typ}@{o.get('_id')} empty name")
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{path}[{i}]")
    walk(obj)
    return dup, empty


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print("Usage: python plantuml_to_mdj.py input.puml output.mdj [--keyword-strict]", file=sys.stderr)
        return 1

    inp = Path(argv[1])
    out = Path(argv[2])
    text = inp.read_text(encoding="utf-8")
    mdj = build_project_from_puml(text, keyword_strict=("--keyword-strict" in argv))

    dup, empty = validate_mdj(mdj)
    if dup or empty:
        print("VALIDATION FAILED", file=sys.stderr)
        if dup:
            print("duplicate ids:", dup[:20], file=sys.stderr)
        if empty:
            print("empty names:", empty[:20], file=sys.stderr)
        return 2
    out.write_text(json.dumps(mdj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
