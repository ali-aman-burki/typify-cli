import sys
import argparse

from typify_prototype import infer_project

sys.setrecursionlimit(5000)


def main():
    parser = argparse.ArgumentParser(
        prog="typify-prototype",
        description="Typify: Static Type Inference for Python projects.",
    )
    parser.add_argument("input_dir", help="Python project to analyse.")
    parser.add_argument(
        "output_dir",
        help="Directory where output JSON files will be written.",
    )
    args = parser.parse_args()

    infer_project(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
