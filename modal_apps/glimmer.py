# Self-host Muse Glimmer 30B (open weights, Apache 2.0) on Modal with vLLM.
#
#   uv run modal deploy modal_apps/glimmer.py   # prints the URL -> put it in GLIMMER_URL
#   uv run modal app stop fall-zero-glimmer     # stop paying for the GPU
#
# Glimmer needs ~72 GB VRAM, so one H100 (80 GB) fits with a capped context length.
# Released vLLM wheels don't support Glimmer yet; Meta publishes a vLLM image that does.
# The server needs auth: call it with the same Modal proxy token as the shared endpoint
# (`Authorization: Bearer wk-<id>.ws-<secret>`). The first start downloads ~60 GB of
# weights into the volume; later cold starts reuse them.

import subprocess

import modal

MODEL_ID = "meta-models/Muse-Glimmer-30B"
SERVED_NAME = "muse-glimmer"
GPU = "H100"
MAX_MODEL_LEN = 65_536  # raise toward 131072 on a bigger GPU (e.g. "H200")
PORT = 8000
MINUTES = 60

image = (
    modal.Image.from_registry("vllm/vllm-openai:muse-glimmer")
    .entrypoint([])  # the image's ENTRYPOINT is `vllm serve`; we launch it ourselves
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)
hf_cache = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)

app = modal.App("fall-zero-glimmer")


@app.server(
    image=image,
    gpu=GPU,
    port=PORT,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
    startup_timeout=30 * MINUTES,  # covers the first weight download
    scaledown_window=10 * MINUTES,  # scales to zero after 10 idle minutes
    target_concurrency=32,
)
class Glimmer:
    @modal.enter()
    def start(self):
        cmd = [
            "vllm",
            "serve",
            MODEL_ID,
            "--served-model-name",
            SERVED_NAME,
            "--host",
            "0.0.0.0",
            "--port",
            str(PORT),
            "--tensor-parallel-size",
            "1",
            "--max-model-len",
            str(MAX_MODEL_LEN),
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            "muse_glimmer",  # underscores: vLLM matches these literally
            "--reasoning-parser",
            "muse_glimmer",
            "--generation-config",
            "auto",  # use the checkpoint's sampling settings
        ]
        print(*cmd)
        self.process = subprocess.Popen(cmd)

    @modal.exit()
    def stop(self):
        self.process.terminate()
