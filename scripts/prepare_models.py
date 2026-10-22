"""Download two compact open models; no fine-tuning or source data leaves QUFO."""
import os
from pathlib import Path
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path(os.getenv("QUFO_MODELS", str(ROOT / "models")))
for repo, folder in [
    ("sentence-transformers/all-MiniLM-L6-v2", "embeddings"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "generation"),
]:
    print(f"Preparing {repo}", flush=True)
    snapshot_download(repo_id=repo, local_dir=MODELS / folder,
                      allow_patterns=["README.md", "LICENSE", "LICENSE*", "*.json", "*.safetensors", "*.txt", "*.model", "merges.txt", "vocab.json", "1_Pooling/*", "2_Normalize/*"],
                      ignore_patterns=["onnx/*", "openvino/*"], max_workers=2)
print("QUFO models are ready.", flush=True)
