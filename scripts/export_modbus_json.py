#!/usr/bin/env python3
"""Export the SH10RT reference CSVs as typed JSON. No device or network access."""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "reference"


def read_csv(name):
    with (REFERENCE / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def build_catalog():
    registers = []
    for row in read_csv("modbus-registers.csv"):
        item = dict(row)
        for key in ("logical_address", "pdu_address", "register_count"):
            item[key] = int(item[key])
        item["read_function"] = int(item["read_function"], 16)
        item["multiplier"] = float(item["multiplier"])
        item["source_ids"] = item.pop("source").split(";")
        item["access"] = "read_only" if item["register_space"] == "input" else "read_write"
        registers.append(item)

    flags = []
    for row in read_csv("modbus-flags.csv"):
        item = dict(row)
        for key in ("input_word", "pdu_address", "word_bit", "u32_base_register", "u32_bit"):
            item[key] = int(item[key])
        item["word_mask"] = int(item["word_mask_hex"], 16)
        item["source_ids"] = item.pop("source").split(";")
        flags.append(item)

    return {
        "schema_version": 1,
        "description": "SH10RT register reference; support depends on model, firmware and interface.",
        "addressing": {
            "logical_base": 1,
            "pdu_base": 0,
            "pdu_offset_from_logical": -1,
            "bytes_per_register": 2,
            "byte_order_within_register": "big_endian",
            "word_order_for_32bit_values": "low_word_first",
            "bit_numbering_base": 0,
        },
        "sources_file": "modbus-sources.json",
        "registers": registers,
        "flags": flags,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check that the JSON matches the CSVs without writing.")
    args = parser.parse_args()
    output = REFERENCE / "modbus-registers.json"
    rendered = json.dumps(build_catalog(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print("JSON is missing or differs from the CSVs. Run scripts/export_modbus_json.py.")
            return 1
        print("JSON matches both reference CSVs.")
        return 0
    output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
