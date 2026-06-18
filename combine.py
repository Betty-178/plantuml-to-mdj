#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Combine class+state diagrams with sequence diagrams into one .mdj.

Usage:
    python combine.py <class_state.puml> <output.mdj> [seq.puml]

The sequence diagram is placed at the Project root level (sibling of UMLModel),
named Collaboration1 / Interaction1 / SequenceDiagram1 as required by the spec.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from plantuml_to_mdj import (
    build_project_from_puml,
    parse_sequence_puml,
    build_sequence_mdj,
    validate_mdj,
)


def find_model(project):
    for elem in project.get("ownedElements", []):
        if elem.get("_type") == "UMLModel":
            return elem
    return None


def add_sequence_to_project_root(project, seq_puml_path):
    """Parse sequence puml and add Collaboration1 directly to Project root."""
    project_id = project["_id"]

    text = Path(seq_puml_path).read_text(encoding="utf-8")
    seq_data = parse_sequence_puml(text)
    seq_project = build_sequence_mdj(seq_data)

    seq_model = find_model(seq_project)
    if seq_model is None:
        return

    for elem in seq_model.get("ownedElements", []):
        if elem.get("_type") != "UMLCollaboration":
            continue
        # Re-parent to Project root
        elem["_parent"] = {"$ref": project_id}
        elem["name"] = "Collaboration1"
        for sub in elem.get("ownedElements", []):
            if sub.get("_type") == "UMLInteraction":
                sub["name"] = "Interaction1"
                for sub2 in sub.get("ownedElements", []):
                    if sub2.get("_type") == "UMLSequenceDiagram":
                        sub2["name"] = "SequenceDiagram1"
                        sub2["_parent"] = {"$ref": sub["_id"]}
        project["ownedElements"].append(elem)
        break


def main(argv):
    if len(argv) < 3:
        print("Usage: combine.py <class_state.puml> <output.mdj> [seq.puml]",
              file=sys.stderr)
        return 1

    class_state_puml = Path(argv[1])
    output_mdj = Path(argv[2])
    seq_puml = argv[3] if len(argv) > 3 else None

    text = class_state_puml.read_text(encoding="utf-8")
    project = build_project_from_puml(text)
    project.setdefault("documentVersion", 1)

    if seq_puml:
        add_sequence_to_project_root(project, seq_puml)

    dup, empty = validate_mdj(project)
    if dup or empty:
        print("VALIDATION FAILED", file=sys.stderr)
        if dup:
            print("duplicate ids:", dup[:20], file=sys.stderr)
        if empty:
            print("empty names:", empty[:20], file=sys.stderr)
        return 2

    output_mdj.write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {output_mdj}")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
