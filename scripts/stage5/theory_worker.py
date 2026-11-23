#!/usr/bin/env python3
"""Synchronous pre-initialization hook used by the Stage 5 native backend."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.theory.cache import bind

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["bind"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    bind(args.directory.resolve())
