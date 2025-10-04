"""Validation utilities for GPU trace files in JETS format.

JETS (JSON Event Trace Streaming) is a streaming JSON Lines format
for GPU microarchitecture traces.
"""

import json
from typing import Dict, Set


class ValidationError(Exception):
    """Raised when trace validation fails."""
    pass


def validate_trace(file_path: str) -> None:
    """Validate a JETS trace file for correctness.

    Args:
        file_path: Path to trace file (.jets or .jsonl)

    Raises:
        ValidationError: If validation fails
    """
    seen_ids: Set[str] = set()
    record_ends: Dict[str, int] = {}
    line_num = 0

    with open(file_path, 'r') as f:
        # Check header
        line = f.readline()
        line_num += 1

        if not line:
            raise ValidationError("Empty file")

        try:
            header = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Line {line_num}: Invalid JSON: {e}")

        if header.get('type') != 'header':
            raise ValidationError(f"Line {line_num}: First line must be header, got {header.get('type')}")

        if header.get('version') != '2.0':
            raise ValidationError(f"Line {line_num}: Expected version 2.0, got {header.get('version')}")

        # Process remaining lines
        for line in f:
            line_num += 1

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValidationError(f"Line {line_num}: Invalid JSON: {e}")

            obj_type = obj.get('type')

            if obj_type == 'record':
                # Validate record
                record_id = obj.get('id')
                if not record_id:
                    raise ValidationError(f"Line {line_num}: Record missing 'id'")

                if record_id in seen_ids:
                    raise ValidationError(f"Line {line_num}: Duplicate ID '{record_id}'")

                seen_ids.add(record_id)

                parent_id = obj.get('parent_id')
                if parent_id is not None and parent_id not in seen_ids:
                    raise ValidationError(f"Line {line_num}: Unknown parent '{parent_id}'")

                if 'record_type' not in obj:
                    raise ValidationError(f"Line {line_num}: Record missing 'record_type'")

                if 'clk' not in obj:
                    raise ValidationError(f"Line {line_num}: Record missing 'clk'")

                if 'name' not in obj:
                    raise ValidationError(f"Line {line_num}: Record missing 'name'")

            elif obj_type == 'record_end':
                # Validate record_end
                record_id = obj.get('id')
                if not record_id:
                    raise ValidationError(f"Line {line_num}: record_end missing 'id'")

                if record_id not in seen_ids:
                    raise ValidationError(f"Line {line_num}: Unknown record '{record_id}'")

                if record_id in record_ends:
                    raise ValidationError(f"Line {line_num}: Duplicate record_end for '{record_id}'")

                if 'clk' not in obj:
                    raise ValidationError(f"Line {line_num}: record_end missing 'clk'")

                record_ends[record_id] = obj['clk']

            elif obj_type == 'annotation':
                # Validate annotation
                record_id = obj.get('record_id')
                if not record_id:
                    raise ValidationError(f"Line {line_num}: annotation missing 'record_id'")

                if record_id not in seen_ids:
                    raise ValidationError(f"Line {line_num}: Unknown record '{record_id}'")

                if 'name' not in obj:
                    raise ValidationError(f"Line {line_num}: annotation missing 'name'")

                if 'data' not in obj:
                    raise ValidationError(f"Line {line_num}: annotation missing 'data'")

            elif obj_type == 'event':
                # Validate event
                record_id = obj.get('record_id')
                if not record_id:
                    raise ValidationError(f"Line {line_num}: event missing 'record_id'")

                if record_id not in seen_ids:
                    raise ValidationError(f"Line {line_num}: Unknown record '{record_id}'")

                if 'name' not in obj:
                    raise ValidationError(f"Line {line_num}: event missing 'name'")

                if 'clk' not in obj:
                    raise ValidationError(f"Line {line_num}: event missing 'clk'")

            elif obj_type == 'footer':
                # Footer must be last line
                next_line = f.readline()
                if next_line:
                    raise ValidationError(f"Line {line_num}: Footer must be last line")

            else:
                raise ValidationError(f"Line {line_num}: Unknown type '{obj_type}'")


def validate_trace_verbose(file_path: str) -> str:
    """Validate trace and return summary message.

    Args:
        file_path: Path to trace file (.jets or .jsonl)

    Returns:
        Validation summary message
    """
    try:
        validate_trace(file_path)

        # Count lines
        with open(file_path, 'r') as f:
            lines = sum(1 for _ in f)

        return f"Validation passed: {lines} lines"

    except ValidationError as e:
        return f"Validation failed: {e}"
