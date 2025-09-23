#!/usr/bin/env python3
"""
Generate PNG snapshots of WaveScout waveform viewer from saved sessions.

Usage:
    python take_snapshot.py [--backend wellen|libfst] <session.json> [output.png]
    
Args:
    --backend    - FST backend to use: 'wellen' (pyrox) or 'libfst' (pylibfst)
    session.json - WaveScout session file (auto-detected if omitted)
    output.png   - Output image path (default: snapshot.png)

Renders a 1200x800 WaveScout widget with the loaded session and saves it as PNG.
Useful for documentation, testing, and sharing waveform views.
"""

import sys
import time
import argparse
from pathlib import Path
from typing import Optional, Literal
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from wavescout import WaveScoutWidget, load_session
from wavescout.timing_utils import set_startup_time, tprint

# Global startup time for tracking elapsed time
startup_time = None

def take_snapshot(session_file: str, output_file: str = "snapshot.png",
                  backend: Optional[Literal["wellen", "libfst"]] = None):
    """Load a session and take a snapshot of the widget."""
    global startup_time
    start_time = time.time()
    app = QApplication(sys.argv)
    
    # Apply dark theme
    app.setStyle("Fusion")
    
    # Create widget
    tprint("Creating WaveScoutWidget...")
    widget = WaveScoutWidget()
    widget.resize(1200, 800)
    tprint("Widget created and resized")

    # Load session with backend preference
    tprint(f"Loading session from: {session_file}")
    if backend:
        tprint(f"Using backend: {backend}")
        backend_pref = "pyrox" if backend == "wellen" else "pylibfst"
        session = load_session(Path(session_file), backend_preference=backend_pref)
    else:
        session = load_session(Path(session_file))
    tprint("Session loaded")

    tprint("Setting session on widget...")
    widget.setSession(session)
    tprint("Session set on widget")

    # Show widget (needed for rendering)
    tprint("Showing widget...")
    show_start = time.time()
    widget.show()
    tprint(f"Widget.show() completed (took {time.time() - show_start:.3f}s)")

    # Process events to ensure proper layout
    tprint("Processing events...")
    process_start = time.time()
    app.processEvents()
    tprint(f"app.processEvents() completed (took {time.time() - process_start:.3f}s)")
    
    # Use a timer to take the snapshot after the widget is fully rendered
    def grab_snapshot():
        tprint("Starting snapshot capture...")
        grab_start = time.time()
        pixmap = widget.grab()
        tprint(f"widget.grab() completed (took {time.time() - grab_start:.3f}s)")

        tprint("Saving snapshot...")
        save_start = time.time()
        pixmap.save(output_file)
        tprint(f"pixmap.save() completed (took {time.time() - save_start:.3f}s)")

        tprint(f"Snapshot saved to: {output_file}")
        elapsed_time = time.time() - start_time
        tprint(f"Total runtime: {elapsed_time:.3f} seconds")
        app.quit()

    tprint("Setting up QTimer...")
    timer_start = time.time()
    QTimer.singleShot(50, grab_snapshot)
    tprint(f"QTimer setup completed (took {time.time() - timer_start:.3f}s)")

    tprint("Starting app.exec()...")
    exec_start = time.time()
    app.exec()
    tprint(f"app.exec() finished (ran for {time.time() - exec_start:.3f}s)")


if __name__ == "__main__":
    # Set global startup time
    startup_time = time.time()
    script_start_time = startup_time
    set_startup_time(startup_time)  # Set it globally for all modules

    tprint("Script started")
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
            tprint(f"No session file specified, using: {session_file}")
        else:
            print("Error: No session file specified and no .json files found in current directory")
            parser.print_help()
            sys.exit(1)
    else:
        session_file = args.session_file

    take_snapshot(session_file, args.output_file, backend=args.backend)

    # Print total script runtime including argument parsing
    total_runtime = time.time() - script_start_time
    tprint(f"Script total runtime: {total_runtime:.3f} seconds")