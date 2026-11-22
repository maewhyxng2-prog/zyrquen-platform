#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — NAGI v10 Dataset Generator

Purpose:
Generate a deterministic symbolic relational-reasoning dataset.

Outputs:
data/nagi_v10/train.jsonl
data/nagi_v10/validation.jsonl
data/nagi_v10/test.jsonl
data/nagi_v10/manifest.json

Safety:
- Does not modify v7, v8, or v9.
- Does not overwrite an existing v10 dataset.
- Uses only Python standard library.
- Does not start model training.
- Dataset is a research prototype, not proof of general intelligence.
"""

from future import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(file).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "nagi_v10"

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 42

DEFAULT_COUNTS = {
"train": 400,
"validation": 50,
"test": 50,
}

Each split receives a disjoint entity namespace.

ENTITY_PREFIXES = {
"train": "TR",
"validation": "VA",
"test": "TE",
}

Prompt templates are deliberately separated by split.

The underlying relational operation remains the same.

TEMPLATES = {
"train": [
"Find the final entity by following the relations.",
"Determine which entity is reachable from the starting entity.",
],
"validation": [
"Trace the given connections and identify the destination.",
"Which entity can be reached by following all listed links?",
],
"test": [
"Resolve the complete connection path and return its endpoint.",
"Starting from the first node, where does the full path lead?",
],
}

def canonical_json(data: Any) -> bytes:
"""Serialize data deterministically."""
return json.dumps(
data,
ensure_ascii=False,
sort_keys=True,
separators=(",", ":"),
).encode("utf-8")

def sha256_bytes(data: bytes) -> str:
return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
digest = hashlib.sha256()

with path.open("rb") as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b""):
        digest.update(chunk)

return digest.hexdigest()

def make_entity(split: str, example_index: int, node_index: int) -> str:
prefix = ENTITY_PREFIXES[split]
return f"{prefix}{example_index:06d}{node_index:02d}"

def generate_example(
split: str,
example_index: int,
rng: random.Random,
) -> dict[str, Any]:
"""
Generate a three-hop directed path with unrelated distractor edges.

The correct answer is obtained by composing the relations,
not by selecting an entity based on its position in the input.
"""

node_count = 8

entities = [
    make_entity(split, example_index, index)
    for index in range(node_count)
]

# Select a path with three directed edges.
path_nodes = rng.sample(range(node_count), 4)

path_edges = [
    (path_nodes[0], path_nodes[1]),
    (path_nodes[1], path_nodes[2]),
    (path_nodes[2], path_nodes[3]),
]

edges = set(path_edges)

# Add distractor edges that do not change the intended answer.
possible_edges = [
    (source, target)
    for source in range(node_count)
    for target in range(node_count)
    if source != target
    and (source, target) not in edges
]

rng.shuffle(possible_edges)

for edge in possible_edges:
    if len(edges) >= 7:
        break

    # Avoid adding a direct shortcut from start to destination.
    if edge == (path_nodes[0], path_nodes[3]):
        continue

    edges.add(edge)

edge_list = list(edges)
rng.shuffle(edge_list)

facts = [
    {
        "relation": "linked_to",
        "source": entities[source],
        "target": entities[target],
    }
    for source, target in edge_list
]

template_index = rng.randrange(len(TEMPLATES[split]))

return {
    "schema_version": "1.0",
    "example_id": f"{split}_{example_index:06d}",
    "split": split,
    "task_type": "relational_chain",
    "reasoning_operator": "directed_path_composition",
    "template_id": f"{split}_template_{template_index:02d}",
    "instruction": TEMPLATES[split][template_index],
    "facts": facts,
    "query": {
        "relation": "linked_to",
        "source": entities[path_nodes[0]],
        "hops": 3,
    },
    "answer": entities[path_nodes[3]],
    "metadata": {
        "entity_namespace": ENTITY_PREFIXES[split],
        "path_length": 3,
        "distractor_edge_count": len(edge_list) - 3,
        "seed": DEFAULT_SEED,
    },
}

def validate_example(example: dict[str, Any]) -> None:
required_fields = {
"schema_version",
"example_id",
"split",
"task_type",
"reasoning_operator",
"template_id",
"instruction",
"facts",
"query",
"answer",
"metadata",
}

missing = required_fields - set(example)

if missing:
    raise ValueError(
        f"Example {example.get('example_id')} missing fields: "
        f"{sorted(missing)}"
    )

if example["task_type"] != "relational_chain":
    raise ValueError("Unexpected task type")

if example["query"]["hops"] != 3:
    raise ValueError("Unexpected path length")

if not isinstance(example["facts"], list):
    raise ValueError("facts must be a list")

if len(example["facts"]) < 3:
    raise ValueError("Insufficient relation facts")

if not example["answer"]:
    raise ValueError("Empty answer")

def verify_path(example: dict[str, Any]) -> bool:
"""Verify that the expected answer is reachable in exactly 3 hops."""

adjacency: dict[str, list[str]] = {}

for fact in example["facts"]:
    adjacency.setdefault(fact["source"], []).append(
        fact["target"]
    )

start = example["query"]["source"]
current_nodes = {start}

for _ in range(example["query"]["hops"]):
    next_nodes: set[str] = set()

    for node in current_nodes:
        next_nodes.update(adjacency.get(node, []))

    current_nodes = next_nodes

return example["answer"] in current_nodes

def generate_split(
split: str,
count: int,
seed: int,
) -> list[dict[str, Any]]:
rng = random.Random(seed)
examples = []

for index in range(count):
    example = generate_example(split, index, rng)
    validate_example(example)

    if not verify_path(example):
        raise ValueError(
            f"Generated path verification failed: "
            f"{example['example_id']}"
        )

    examples.append(example)

return examples

def write_jsonl(path: Path, examples: list[dict[str, Any]]) -> None:
with path.open("x", encoding="utf-8", newline="\n") as file:
for example in examples:
file.write(
json.dumps(
example,
ensure_ascii=False,
sort_keys=True,
)
)
file.write("\n")

def check_split_isolation(
splits: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
"""
Verify entity and template separation.

Note:
    The reasoning operator is intentionally shared across splits.
    This dataset measures transfer of the same abstract operation
    to unseen entities and unseen instruction templates.

    It does NOT claim unseen abstract-operator generalization.
"""

entity_sets: dict[str, set[str]] = {}
template_sets: dict[str, set[str]] = {}

for split, examples in splits.items():
    entities: set[str] = set()
    templates: set[str] = set()

    for example in examples:
        templates.add(example["template_id"])

        entities.add(example["query"]["source"])
        entities.add(example["answer"])

        for fact in example["facts"]:
            entities.add(fact["source"])
            entities.add(fact["target"])

    entity_sets[split] = entities
    template_sets[split] = templates

isolation_results = {}

split_names = list(splits)

for index, left in enumerate(split_names):
    for right in split_names[index + 1:]:
        entity_overlap = entity_sets[left] & entity_sets[right]
        template_overlap = (
            template_sets[left] & template_sets[right]
        )

        key = f"{left}__{right}"

        isolation_results[key] = {
            "entity_overlap_count": len(entity_overlap),
            "template_overlap_count": len(template_overlap),
            "entity_isolation_pass": not entity_overlap,
            "template_isolation_pass": not template_overlap,
        }

        if entity_overlap or template_overlap:
            raise ValueError(
                f"Split isolation failed: {key}"
            )

return isolation_results

def build_manifest(
splits: dict[str, list[dict[str, Any]]],
output_files: dict[str, Path],
seed: int,
isolation: dict[str, Any],
) -> dict[str, Any]:

file_records = {}

for split, path in output_files.items():
    file_records[split] = {
        "path": path.name,
        "example_count": len(splits[split]),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }

total_examples = sum(
    len(examples) for examples in splits.values()
)

return {
    "project": "ZYRQUEN Ω∞",
    "dataset": "nagi_v10",
    "generator": "gen_nagi_v10.py",
    "generator_version": GENERATOR_VERSION,
    "schema_version": "1.0",
    "created_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "seed": seed,
    "total_examples": total_examples,
    "task_types": [
        "relational_chain",
    ],
    "reasoning_operators": [
        "directed_path_composition",
    ],
    "generalization_scope": {
        "unseen_entities": True,
        "unseen_instruction_templates": True,
        "unseen_abstract_operators": False,
        "description": (
            "Shared directed-path composition operator with "
            "disjoint entities and instruction templates."
        ),
    },
    "split_isolation": isolation,
    "splits": file_records,
    "integrity": {
        "algorithm": "SHA-256",
        "manifest_self_hash": (
            "Not included; hash manifest externally if required."
        ),
    },
    "limitations": [
        "This is a symbolic relational-reasoning prototype.",
        "It does not measure all NGI capabilities.",
        "It does not establish general intelligence.",
        "Independent leakage audit is still required.",
        "Architecture compatibility has not been established.",
    ],
}

def parse_args() -> argparse.Namespace:
parser = argparse.ArgumentParser(
description="Generate the ZYRQUEN NAGI v10 dataset."
)

parser.add_argument(
    "--output",
    type=Path,
    default=DEFAULT_OUTPUT,
    help="Output directory. Must not already exist.",
)

parser.add_argument(
    "--seed",
    type=int,
    default=DEFAULT_SEED,
)

parser.add_argument(
    "--train-count",
    type=int,
    default=DEFAULT_COUNTS["train"],
)

parser.add_argument(
    "--validation-count",
    type=int,
    default=DEFAULT_COUNTS["validation"],
)

parser.add_argument(
    "--test-count",
    type=int,
    default=DEFAULT_COUNTS["test"],
)

return parser.parse_args()

def main() -> int:
args = parse_args()

counts = {
    "train": args.train_count,
    "validation": args.validation_count,
    "test": args.test_count,
}

if args.seed < 0:
    print("ERROR: seed must be non-negative", file=sys.stderr)
    return 2

if any(count <= 0 for count in counts.values()):
    print(
        "ERROR: all split counts must be positive",
        file=sys.stderr,
    )
    return 2

output_dir = args.output.resolve()

if output_dir.exists():
    print(
        f"BLOCKED: output directory already exists: {output_dir}",
        file=sys.stderr,
    )
    print(
        "Refusing to overwrite existing dataset artifacts.",
        file=sys.stderr,
    )
    return 3

try:
    splits = {}

    seed_offsets = {
        "train": 0,
        "validation": 100_000,
        "test": 200_000,
    }

    for split, count in counts.items():
        splits[split] = generate_split(
            split=split,
            count=count,
            seed=args.seed + seed_offsets[split],
        )

    isolation = check_split_isolation(splits)

    output_dir.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_dir.mkdir(
        parents=False,
        exist_ok=False,
    )

    output_files = {}

    for split in ("train", "validation", "test"):
        path = output_dir / f"{split}.jsonl"

        write_jsonl(path, splits[split])
        output_files[split] = path

    manifest = build_manifest(
        splits=splits,
        output_files=output_files,
        seed=args.seed,
        isolation=isolation,
    )

    manifest_path = output_dir / "manifest.json"

    with manifest_path.open(
        "x",
        encoding="utf-8",
        newline="\n",
    ) as file:
        json.dump(
            manifest,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    print("NAGI v10 DATASET GENERATION COMPLETED")
    print(f"Output: {output_dir}")
    print(f"Total examples: {manifest['total_examples']}")

    for split, record in manifest["splits"].items():
        print(
            f"{split}: {record['example_count']} examples "
            f"| SHA-256: {record['sha256']}"
        )

    print("Entity isolation: PASS")
    print("Template isolation: PASS")
    print("Path verification: PASS")
    print("Abstract operator isolation: NOT CLAIMED")
    print("Training: NOT STARTED")
    print("Independent leakage audit: PENDING")

    return 0

except FileExistsError:
    print(
        "BLOCKED: output path already exists; no overwrite performed.",
        file=sys.stderr,
    )
    return 3

except Exception as exc:
    print(
        f"FAILED: {type(exc).__name__}: {exc}",
        file=sys.stderr,
    )
    return 1

if name == "main":
raise SystemExit(main())
