"""Download the pinned wig visual model without starting the production service."""
from huggingface_hub import snapshot_download


if __name__ == "__main__":
    path = snapshot_download(
        repo_id="Qwen/Qwen3-VL-2B-Instruct",
        revision="main",
        cache_dir=r"F:\models\huggingface",
    )
    print(path, flush=True)
