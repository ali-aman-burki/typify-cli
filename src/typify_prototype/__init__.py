import json
from pathlib import Path

from typify_prototype.utils.utils import Utils
from typify_prototype.preprocessing.preloader import Preloader
from typify_prototype.inferencing.inferencer import Inferencer

package_dir = str(Path(__file__).parent.parent)
stubs_dir = str(package_dir + "/typifystubs")

DEFAULT_CONFIG = {
    "paths": [f"{stubs_dir}/stdlib/"],
    "inference": {
        "builtins": f"{stubs_dir}/stdlib/builtins.pyi",
        "typing": f"{stubs_dir}/stdlib/typing.pyi",
        "types": f"{stubs_dir}/stdlib/types.pyi",
        "collections.abc": f"{stubs_dir}/stdlib/collections/abc.pyi",
        "__future__": f"{stubs_dir}/stdlib/__future__.pyi",
    },
}


def run_project(project_dir: Path, config: dict) -> dict:
    if not Utils.is_valid_directory(project_dir):
        print("Invalid project path given.")
        exit(1)

    Preloader.load(config=config, project_dir=project_dir)
    project_lib, corrected_sequences = Inferencer.preinfer()
    return Inferencer.infer(project_lib, corrected_sequences)


def infer_project(input_dir, output_dir):
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path = output_dir / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config = DEFAULT_CONFIG.copy()
        config.update(user_config)
    else:
        config = DEFAULT_CONFIG.copy()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent="\t")

    inferred = run_project(project_dir=input_dir, config=config)

    entries = list(inferred.items())
    pad = len(str(len(entries) - 1)) if entries else 1

    index = {}
    for i, (abs_src, buckets) in enumerate(entries):
        json_name = f"{str(i).zfill(pad)}.json"
        with open(output_dir / json_name, "w", encoding="utf-8") as f:
            json.dump(buckets, f, indent="\t")
        try:
            rel_src = Path(abs_src).relative_to(input_dir).as_posix()
        except ValueError:
            rel_src = Path(abs_src).as_posix()
        index[rel_src] = json_name

    with open(output_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent="\t")
