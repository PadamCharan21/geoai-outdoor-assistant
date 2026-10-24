"""Copy a public <=3B base model into a public HF repo with our model card."""
import argparse
import shutil
import tempfile
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = "Qwen/Qwen2.5-0.5B-Instruct"
ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("repo_id", help="Public target, e.g. username/fieldnote-geoai-slm")
    args = p.parse_args()
    api = HfApi()
    api.create_repo(args.repo_id, repo_type="model", private=False, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fieldnote-model-") as temp:
        dest = Path(temp) / "repo"
        dest.mkdir()
        model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype="auto")
        tokenizer = AutoTokenizer.from_pretrained(BASE)
        model.save_pretrained(dest, safe_serialization=True)
        tokenizer.save_pretrained(dest)
        card = (ROOT / "model-card" / "README.md").read_text(encoding="utf-8")
        card = card.replace("YOUR-HF-USERNAME/fieldnote-geoai-slm", args.repo_id)
        (dest / "README.md").write_text(card, encoding="utf-8")
        license_path = hf_hub_download(repo_id=BASE, filename="LICENSE")
        shutil.copy2(license_path, dest / "LICENSE")
        api.upload_folder(folder_path=str(dest), repo_id=args.repo_id, repo_type="model",
                          commit_message="Publish Fieldnote GeoAI base model and model card")

if __name__ == "__main__":
    main()

