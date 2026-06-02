from __future__ import annotations
from dataclasses import dataclass, asdict

import ast
import joblib
import json

import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy import sparse

from .preprocessing.typeexpr import parse_typeexpr

@dataclass
class BuildConfig:
	max_features: int = 20000
	ngram_range: tuple[int, int] = (1, 2)
	min_df: int = 1
	use_sublinear_tf: bool = False
	lowercase: bool = True
	norm: str = "l2"

	def save(self, path: Path):
		path.write_text(json.dumps(asdict(self), indent=2))

	@classmethod
	def load(cls, path: Path):
		return cls(**json.loads(path.read_text()))

def extract_typed_slots(file_path: Path):
	try:
		source = file_path.read_text(encoding="utf8")
	except Exception:
		return []

	try:
		tree = ast.parse(source, filename=str(file_path))
	except SyntaxError:
		return []

	slots: list[tuple[str, str, str]] = []

	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef):
			func_name = node.name

			for arg in getattr(node.args, "posonlyargs", []):
				if arg.annotation:
					raw = ast.unparse(arg.annotation)
					t = parse_typeexpr(raw)
					ctx = f"function {func_name} posonlyarg {arg.arg}"
					slots.append((f"{file_path}:{func_name}:{arg.arg}", ctx, str(t)))

			for arg in node.args.args:
				if arg.annotation:
					raw = ast.unparse(arg.annotation)
					t = parse_typeexpr(raw)
					ctx = f"function {func_name} param {arg.arg}"
					slots.append((f"{file_path}:{func_name}:{arg.arg}", ctx, str(t)))

			if node.args.vararg and node.args.vararg.annotation:
				raw = ast.unparse(node.args.vararg.annotation)
				t = parse_typeexpr(raw)
				ctx = f"function {func_name} vararg *{node.args.vararg.arg}"
				slots.append((f"{file_path}:{func_name}:*{node.args.vararg.arg}", ctx, str(t)))

			for arg in node.args.kwonlyargs:
				if arg.annotation:
					raw = ast.unparse(arg.annotation)
					t = parse_typeexpr(raw)
					ctx = f"function {func_name} kwonlyarg {arg.arg}"
					slots.append((f"{file_path}:{func_name}:{arg.arg}", ctx, str(t)))

			if node.args.kwarg and node.args.kwarg.annotation:
				raw = ast.unparse(node.args.kwarg.annotation)
				t = parse_typeexpr(raw)
				ctx = f"function {func_name} kwarg **{node.args.kwarg.arg}"
				slots.append((f"{file_path}:{func_name}:**{node.args.kwarg.arg}", ctx, str(t)))

			if node.returns:
				raw = ast.unparse(node.returns)
				t = parse_typeexpr(raw)
				ctx = f"function {func_name} return"
				slots.append((f"{file_path}:{func_name}:return", ctx, str(t)))

		elif isinstance(node, ast.AnnAssign):
			if isinstance(node.target, ast.Name):
				name = node.target.id
				raw = ast.unparse(node.annotation)
				t = parse_typeexpr(raw)
				ctx = f"variable {name}"
				slots.append((f"{file_path}:{name}", ctx, str(t)))

	return slots


def build_csv_index(train_list_file: str, output_csv: Path) -> pd.DataFrame:
	list_path = Path(train_list_file)
	assert list_path.exists(), f"List file not found: {train_list_file}"

	all_files = [
		Path(p.strip()) for p in list_path.read_text().splitlines()
		if p.strip() and not p.strip().startswith("#")
	]

	all_slots: list[tuple[str, str, str]] = []

	for path in tqdm(
		all_files,
		desc="Extracting",
		ascii=(' ', '━'),
		bar_format="{desc}: [{bar:50}] {n_fmt}/{total_fmt}"
	):
		all_slots.extend(extract_typed_slots(path))

	if not all_slots:
		raise RuntimeError("No annotated slots found in the given file list0.")

	df = pd.DataFrame(all_slots, columns=["slot_id", "context_text", "type_label"])
	df["context_text"] = df["context_text"].str.replace(r"\s+", " ", regex=True).str.strip()
	df["type_label"] = df["type_label"].str.replace(r"\s+", " ", regex=True).str.strip()
	df = df.sort_values("slot_id").reset_index(drop=True)

	before = len(df)
	df = df.drop_duplicates().reset_index(drop=True)
	print(f"🧹 Removed {before - len(df)} exact duplicate rows.")

	output_csv.parent.mkdir(parents=True, exist_ok=True)
	df.to_csv(output_csv, index=False, encoding="utf8")

	print(f"✅ Indexed {len(df)} annotated type slots → {output_csv}")
	
	return df

def build_vector_index(df: pd.DataFrame, output_dir: Path, *, max_features=20000, ngram_range=(1, 2), min_df=1):
	corpus = df["context_text"].astype(str).tolist()
	slot_ids = df["slot_id"].astype(str).to_numpy()
	type_labels = df["type_label"].astype(str).to_numpy()

	vectorizer = TfidfVectorizer(
		lowercase=True,
		token_pattern=r"\b[a-zA-Z_][a-zA-Z0-9_]+\b",
		ngram_range=ngram_range,
		max_features=max_features,
		min_df=min_df,
		norm="l2",
		dtype=np.float32,
	)

	print("Training TF-IDF vectorizer...")
	X = vectorizer.fit_transform(tqdm(
		corpus,
		desc="Vectorizing",
		ascii=(' ', '━'),
		bar_format="{desc}: [{bar:50}] {percentage:3.0f}%"
	))

	output_dir.mkdir(parents=True, exist_ok=True)
	sparse.save_npz(output_dir / "tfidf_matrix.npz", X)
	np.save(output_dir / "type_labels.npy", type_labels)
	np.save(output_dir / "slot_ids.npy", slot_ids)
	joblib.dump(vectorizer, output_dir / "vectorizer.pkl", compress=3)

	print(f"✅ Saved TF-IDF index to {output_dir}")
	print(f"   • {X.shape[0]:,} samples")
	print(f"   • {len(vectorizer.vocabulary_):,} unique tokens")

	return vectorizer, X, type_labels, slot_ids

def build_index(
    train_list_file: str,
    output_dir: str,
    *,
    config: BuildConfig | None = None,
    max_features: int | None = None,
    ngram_range: tuple[int, int] | None = None,
    min_df: int | None = None,
):
    """
    Build index for context-matching retrieval system with configurable TF-IDF params.
    """
    config = config or BuildConfig()
    if max_features is not None:
        config.max_features = max_features
    if ngram_range is not None:
        config.ngram_range = ngram_range
    if min_df is not None:
        config.min_df = min_df

    output_root = Path(output_dir)
    csv_path = output_root / "type_index.csv"
    vector_dir = output_root / "tfidf_index"
    config_path = output_root / "build_config.json"

    df = build_csv_index(train_list_file, csv_path)

    build_vector_index(
        df,
        vector_dir,
        max_features=config.max_features,
        ngram_range=config.ngram_range,
        min_df=config.min_df,
    )

    config.save(config_path)
    print(f"💾 Saved build configuration to {config_path}")
    print(f"✅ Done! Full index written to {output_root}")
