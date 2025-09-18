#!/usr/bin/env python3
"""Build pyrox before poetry install."""

import subprocess
import sys
from pathlib import Path


def main():
    """Build pyrox using maturin."""
    project_root = Path(__file__).parent.parent
    pyrox_dir = project_root / "pyrox"

    print("Building pyrox...")

    # Build pyrox with maturin
    print(f"Building pyrox in {pyrox_dir}")
    subprocess.run([sys.executable, "-m", "maturin", "develop", "--release"],
                  cwd=pyrox_dir, check=True)

    print("pyrox built successfully!")


if __name__ == "__main__":
    main()