"""SAM 3.1 mask -> SAM 3D Objects mesh, via the Modal app in `modal_apps/sam3d.py`."""

import io
from pathlib import Path

import modal
import numpy as np
from meta_sam_parser import decode_mask_to_raster
from PIL import Image

from fall_zero.meta import Segment

APP_NAME, CLS_NAME = "fall-zero-sam3d", "Sam3D"


def full_frame_mask(seg: Segment, width: int, height: int) -> np.ndarray:
    """SAM returns a box-local mask raster; paste it into a full-size boolean mask."""
    m = seg.mask.mask
    raster = np.frombuffer(decode_mask_to_raster(m), dtype=np.uint8).reshape(m.height, m.width)
    b = seg.mask.bounds
    left, top = int(b.left), int(b.top)
    box_w, box_h = int(b.right) - left, int(b.bottom) - top
    if (box_w, box_h) != (m.width, m.height):  # raster can be coarser than the box
        raster = np.array(Image.fromarray(raster * 255).resize((box_w, box_h), Image.NEAREST)) > 0
    full = np.zeros((height, width), dtype=bool)
    full[top : top + box_h, left : left + box_w] = raster[: height - top, : width - left] > 0
    return full


def reconstruct(image: str | Path, seg: Segment, seed: int = 42) -> dict:
    """Returns {"glb": bytes, "rotation", "translation", "scale"} for one segmented object."""
    img = Image.open(image).convert("RGB")
    mask = full_frame_mask(seg, *img.size)

    image_png, mask_png = io.BytesIO(), io.BytesIO()
    img.save(image_png, format="PNG")
    Image.fromarray(mask.astype(np.uint8) * 255).save(mask_png, format="PNG")

    sam3d = modal.Cls.from_name(APP_NAME, CLS_NAME)()
    return sam3d.reconstruct.remote(image_png.getvalue(), mask_png.getvalue(), seed=seed)
