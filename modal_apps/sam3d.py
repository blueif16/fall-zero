# SAM 3D Objects on Modal: one RGB image + one object mask -> a posed 3D mesh.
#
#   1. Request access at https://huggingface.co/facebook/sam-3d-objects (gated).
#   2. uv run modal secret create huggingface HF_TOKEN=hf_...
#   3. uv run modal run modal_apps/sam3d.py::download_weights   # once, into a Volume
#   4. uv run modal deploy modal_apps/sam3d.py
#
# Call it from Python (see fall_zero/reconstruct.py):
#   modal.Cls.from_name("fall-zero-sam3d", "Sam3D")().reconstruct.remote(image_png, mask_png)
#
# Needs >= 32 GB VRAM. L40S (48 GB) is the cheapest fit and keeps the model on its
# default attention backend; the repo switches to flash_attn on A100/H100/H200.
# The image build compiles pytorch3d and gsplat, so the first build takes a while.

import io

import modal

REPO = "https://github.com/facebookresearch/sam-3d-objects"
COMMIT = "f91db411c50efee93d8db7aeb323885650f6f722"
SRC = "/opt/sam3d"
CKPT = "/checkpoints"
GPU = "L40S"
MINUTES = 60

image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
    .entrypoint([])
    .apt_install("git", "build-essential", "ninja-build", "libgl1", "libglib2.0-0", "libegl1")
    .run_commands(f"git clone {REPO} {SRC} && cd {SRC} && git checkout {COMMIT}")
    .env(
        {
            "PIP_EXTRA_INDEX_URL": "https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121",
            "PIP_FIND_LINKS": "https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html",
            "FORCE_CUDA": "1",  # build CUDA extensions without a GPU attached
            "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9;9.0",
        }
    )
    # Same three-step install as the repo's doc/setup.md
    .run_commands(
        f"cd {SRC} && pip install -e '.[dev]'",
        f"cd {SRC} && pip install --no-build-isolation -e '.[p3d]'",
        f"cd {SRC} && pip install --no-build-isolation -e '.[inference]'",
        f"cd {SRC} && python patching/hydra",
    )
    .pip_install("huggingface-hub[cli]<1.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)
weights = modal.Volume.from_name("sam3d-checkpoints", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")

app = modal.App("fall-zero-sam3d")


@app.function(image=image, volumes={CKPT: weights}, secrets=[hf_secret], timeout=60 * MINUTES)
def download_weights():
    import shutil
    import subprocess
    from pathlib import Path

    if Path(f"{CKPT}/hf/pipeline.yaml").exists():
        print("checkpoints already present")
        return
    subprocess.run(
        ["hf", "download", "--repo-type", "model", "--local-dir", f"{CKPT}/hf-download",
         "--max-workers", "1", "facebook/sam-3d-objects"],
        check=True,
    )
    shutil.move(f"{CKPT}/hf-download/checkpoints", f"{CKPT}/hf")
    shutil.rmtree(f"{CKPT}/hf-download")
    weights.commit()


@app.cls(
    image=image,
    gpu=GPU,
    volumes={CKPT: weights},
    timeout=15 * MINUTES,
    scaledown_window=5 * MINUTES,
)
class Sam3D:
    @modal.enter()
    def load(self):
        import sys

        sys.path.append(f"{SRC}/notebook")
        from inference import Inference

        self.inference = Inference(f"{CKPT}/hf/pipeline.yaml", compile=False)

    @modal.method()
    def reconstruct(self, image_png: bytes, mask_png: bytes, seed: int = 42) -> dict:
        """`mask_png` is a single-channel or RGBA mask the same size as the image; nonzero = object.

        Returns the mesh as GLB bytes plus the object's pose in the camera frame. Scale comes
        from the model's monocular depth (MoGe), so treat it as approximate until it is
        checked against a reference object or listed dimensions.
        """
        import numpy as np
        from PIL import Image

        rgb = np.array(Image.open(io.BytesIO(image_png)).convert("RGB"), dtype=np.uint8)
        mask_img = Image.open(io.BytesIO(mask_png))
        mask_arr = np.array(mask_img.getchannel("A") if mask_img.mode == "RGBA" else mask_img.convert("L"))
        mask = mask_arr > 0
        if mask.shape != rgb.shape[:2]:
            raise ValueError(f"mask {mask.shape} does not match image {rgb.shape[:2]}")

        out = self.inference(rgb, mask, seed=seed)

        glb = io.BytesIO()
        out["glb"].export(glb, file_type="glb")

        def as_list(key):
            v = out.get(key)
            return None if v is None else np.asarray(v.detach().cpu() if hasattr(v, "detach") else v).tolist()

        return {
            "glb": glb.getvalue(),
            "rotation": as_list("rotation"),  # quaternion
            "translation": as_list("translation"),
            "scale": as_list("scale"),
        }
