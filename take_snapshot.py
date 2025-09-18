#!/usr/bin/env python3
"""
Generate PNG snapshots of WaveScout waveform viewer from saved sessions.

Usage:
    python take_snapshot.py [--backend wellen|libfst] <session.yaml> [output.png]
    
Args:
    --backend    - FST backend to use: 'wellen' (pyrox) or 'libfst' (pylibfst)
    session.yaml - WaveScout session file (auto-detected if omitted)
    output.png   - Output image path (default: snapshot.png)

Renders a 1200x800 WaveScout widget with the loaded session and saves it as PNG.
Useful for documentation, testing, and sharing waveform views.
"""

import sys
import argparse
from pathlib import Path
from typing import Optional, Literal
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from wavescout import WaveScoutWidget, load_session

def take_snapshot(session_file: str, output_file: str = "snapshot.png", 
                  backend: Optional[Literal["wellen", "libfst"]] = None):
    """Load a session and take a snapshot of the widget."""
    app = QApplication(sys.argv)
    
    # Apply dark theme
    app.setStyle("Fusion")
    
    # Create widget
    widget = WaveScoutWidget()
    widget.resize(1200, 800)
    
    # Load session with backend preference
    print(f"Loading session from: {session_file}")
    if backend:
        print(f"Using backend: {backend}")
        backend_pref = "pyrox" if backend == "wellen" else "pylibfst"
        session = load_session(Path(session_file), backend_preference=backend_pref)
    else:
        session = load_session(Path(session_file))
    widget.setSession(session)
    
    # Show widget (needed for rendering)
    widget.show()
    
    # Process events to ensure proper layout
    app.processEvents()
    
    # Use a timer to take the snapshot after the widget is fully rendered
    def grab_snapshot():
        pixmap = widget.grab()
        pixmap.save(output_file)
        print(f"Snapshot saved to: {output_file}")
        app.quit()
    
    QTimer.singleShot(50, grab_snapshot)
    app.exec()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate PNG snapshots of WaveScout waveform viewer")
    parser.add_argument("--backend", choices=["wellen", "libfst"], 
                        help="FST backend to use: 'wellen' (pyrox) or 'libfst' (pylibfst)")
    parser.add_argument("session_file", nargs="?", help="WaveScout session file (.json)")
    parser.add_argument("output_file", nargs="?", default="snapshot.png", 
                        help="Output PNG file (default: snapshot.png)")
    
    args = parser.parse_args()
    
    # Handle session file auto-detection
    if not args.session_file:
        # Look for existing session files
        session_files = list(Path(".").glob("*.json"))
        if session_files:
            session_file = str(session_files[0])
            print(f"No session file specified, using: {session_file}")
        else:
            print("Error: No session file specified and no .json files found in current directory")
            parser.print_help()
            sys.exit(1)
    else:
        session_file = args.session_file
    
    take_snapshot(session_file, args.output_file, backend=args.backend)