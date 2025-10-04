"""Streaming trace parser for reading GPU execution traces in JETS format.

JETS (JSON Event Trace Streaming) is a streaming JSON Lines format
for GPU microarchitecture traces.
"""

import json
from typing import Any, Dict, List, Optional, TextIO


class TraceParser:
    """Parses GPU trace data from JETS (JSON Event Trace Streaming) format.

    Usage:
        parser = TraceParser('trace.jets')
        trace = parser.parse()
        print(trace['header'])
        for root in trace['roots']:
            print_tree(root)
    """

    def __init__(self, file_path: str):
        """Initialize trace parser.

        Args:
            file_path: Path to trace file (.jets or .jsonl)
        """
        self.file_path = file_path

    def parse(self) -> Dict[str, Any]:
        """Parse complete trace file and build hierarchical tree.

        Returns:
            Dictionary with:
                - header: Trace metadata
                - roots: List of root record nodes
                - footer: Optional summary statistics
        """
        records_by_id: Dict[str, Dict[str, Any]] = {}
        header: Optional[Dict[str, Any]] = None
        footer: Optional[Dict[str, Any]] = None

        with open(self.file_path, 'r') as f:
            for line in f:
                obj = json.loads(line)

                if obj['type'] == 'header':
                    header = obj

                elif obj['type'] == 'record':
                    record = obj.copy()
                    record['children'] = []
                    record['annotations'] = []
                    record['events'] = []
                    record['end_clk'] = None
                    record['duration'] = None
                    records_by_id[record['id']] = record

                    # Link to parent
                    if record['parent_id'] is not None:
                        parent = records_by_id[record['parent_id']]
                        parent['children'].append(record)

                elif obj['type'] == 'record_end':
                    record = records_by_id[obj['id']]
                    record['end_clk'] = obj['clk']
                    record['duration'] = obj['clk'] - record['clk']

                elif obj['type'] == 'annotation':
                    record = records_by_id[obj['record_id']]
                    record['annotations'].append(obj)

                elif obj['type'] == 'event':
                    record = records_by_id[obj['record_id']]
                    record['events'].append(obj)

                elif obj['type'] == 'footer':
                    footer = obj

        # Return root nodes
        roots = [r for r in records_by_id.values() if r['parent_id'] is None]
        return {
            'header': header,
            'roots': roots,
            'footer': footer
        }

    def parse_streaming(self):
        """Parse trace file line-by-line for real-time processing.

        Yields:
            Parsed objects as they are read (header, records, events, etc.)
        """
        with open(self.file_path, 'r') as f:
            for line in f:
                yield json.loads(line)

    def tail_trace(self, callback):
        """Follow trace file as it's being written (like tail -f).

        Args:
            callback: Function called for each new line object
        """
        import time

        with open(self.file_path, 'r') as f:
            # Read existing content
            for line in f:
                callback(json.loads(line))

            # Follow file as it grows
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                obj = json.loads(line)
                callback(obj)

                # Stop on footer
                if obj['type'] == 'footer':
                    break
