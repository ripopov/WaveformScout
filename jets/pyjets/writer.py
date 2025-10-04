"""Streaming trace writer for GPU execution traces in JETS format.

JETS (JSON Event Trace Streaming) is a streaming JSON Lines format
for GPU microarchitecture traces.
"""

import json
from typing import Any, Dict, Optional, TextIO


class TraceWriter:
    """Writes GPU trace data in JETS (JSON Event Trace Streaming) format.

    Usage:
        writer = TraceWriter('trace.jets')
        writer.write_header({'gpu_model': 'H100', 'tool': 'gpupipe'})
        writer.write_record('rec_001', None, 'HostProgram', clk=1000)
        writer.write_event('rec_001', 'Issue', clk=1015)
        writer.write_record_end('rec_001', clk=1030)
        writer.write_footer(capture_end_clk=1030)
        writer.close()
    """

    def __init__(self, file_path: str):
        """Initialize trace writer.

        Args:
            file_path: Path to output trace file (.jets or .jsonl)
        """
        self.file: TextIO = open(file_path, 'w')
        self.record_count = 0
        self.annotation_count = 0
        self.event_count = 0
        self.record_end_count = 0

    def write_header(self, metadata: Dict[str, Any]) -> None:
        """Write trace header with metadata.

        Args:
            metadata: GPU model, architecture, clock frequency, etc.
        """
        line = json.dumps({
            'type': 'header',
            'version': '2.0',
            'metadata': metadata
        })
        self.file.write(line + '\n')
        self.file.flush()

    def write_record(
        self,
        id: str,
        parent_id: Optional[str],
        record_type: str,
        clk: int,
        name: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Write a record marking the start of an operation.

        Args:
            id: Unique record identifier
            parent_id: Parent record ID (None for root)
            record_type: Type (e.g., 'Warp', 'SASS_Instruction')
            clk: GPU clock cycle when record begins
            name: Human-readable name (required)
            data: Optional arbitrary data dictionary
        """
        record = {
            'type': 'record',
            'id': id,
            'parent_id': parent_id,
            'record_type': record_type,
            'clk': clk,
            'name': name
        }
        if data is not None:
            record['data'] = data

        line = json.dumps(record, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.record_count += 1

    def write_record_end(self, id: str, clk: int) -> None:
        """Write record end marking completion of an operation.

        Args:
            id: Record ID that is ending
            clk: GPU clock cycle when record completes
        """
        line = json.dumps({
            'type': 'record_end',
            'id': id,
            'clk': clk
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.record_end_count += 1

    def write_annotation(
        self,
        record_id: str,
        name: str,
        data: Any
    ) -> None:
        """Write annotation attaching metadata to a record.

        Args:
            record_id: Record ID to annotate
            name: Annotation name (e.g., 'GridDimensions')
            data: Arbitrary annotation data
        """
        line = json.dumps({
            'type': 'annotation',
            'record_id': record_id,
            'name': name,
            'data': data
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.annotation_count += 1

    def write_event(
        self,
        record_id: str,
        name: str,
        clk: int,
        data: Optional[Any] = None
    ) -> None:
        """Write timed event associated with a record.

        Args:
            record_id: Record ID this event belongs to
            name: Event name (e.g., 'DecodeStage', 'L1_Cache_Miss')
            clk: GPU clock cycle when event occurs
            data: Optional event data
        """
        event = {
            'type': 'event',
            'record_id': record_id,
            'name': name,
            'clk': clk
        }
        if data is not None:
            event['data'] = data

        line = json.dumps(event, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.event_count += 1

    def write_footer(self, capture_end_clk: int) -> None:
        """Write optional footer with summary statistics.

        Args:
            capture_end_clk: Final GPU clock timestamp
        """
        line = json.dumps({
            'type': 'footer',
            'capture_end_clk': capture_end_clk,
            'total_records': self.record_count,
            'total_annotations': self.annotation_count,
            'total_events': self.event_count,
            'total_record_ends': self.record_end_count
        })
        self.file.write(line + '\n')
        self.file.flush()

    def close(self) -> None:
        """Close the trace file."""
        self.file.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
