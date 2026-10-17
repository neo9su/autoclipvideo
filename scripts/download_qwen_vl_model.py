"""Download the pinned wig visual model without starting the production service."""
from modelscope import snapshot_download


if __name__ == "__main__":
    path = snapshot_download(
        model_id="Qwen/Qwen3-VL-2B-Instruct-FP8",
        revision="master",
        local_dir=r"F:\models\Qwen3-VL-2B-Instruct-FP8",
        max_workers=4,
    )
    print(path, flush=True)
