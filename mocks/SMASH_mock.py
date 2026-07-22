#!/usr/bin/env python3
"""Mock SMASH executable for testing the stages_of_grief pipeline.

Creates an output directory and an empty output file so downstream
stages have something to consume.
"""

import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Mock SMASH")
    parser.add_argument(
        "--input", "-i", nargs="*", default=None, help="Input file(s) from the previous stage"
    )
    parser.add_argument("--config", "-c", default=None, help="Config file")
    parser.add_argument(
        "--output", "-o", default="smash/output.dat", help="Output file to create"
    )
    args = parser.parse_args()

    print("Running SMASH mock")
    if args.input:
        print(f"  input: {args.input}")
    if args.config:
        print(f"  config: {args.config}")

    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)
    open(args.output, "a").close()
    print(f"  created output: {args.output}")


if __name__ == "__main__":
    main()
