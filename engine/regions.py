from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image


def _point_list(value: Any) -> list[dict]:
    points = []
    for item in value or []:
        try:
            x = float(item["x"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append({"x": x, "y": y})
    return points


def _bbox(value: Any) -> dict | None:
    if not value:
        return None
    try:
        return {
            "x": int(value["x"]),
            "y": int(value["y"]),
            "width": int(value["width"]),
            "height": int(value["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class Region:
    id: str
    name: str
    mask_path: str
    bbox_px: dict | None = None
    positive_points: list[dict] = field(default_factory=list)
    negative_points: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    preview_path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mask_path": self.mask_path,
            "bbox_px": self.bbox_px,
            "positive_points": self.positive_points,
            "negative_points": self.negative_points,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "preview_path": self.preview_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Region":
        now = time.time()
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:10]),
            name=str(data.get("name") or "Region"),
            mask_path=str(data.get("mask_path") or ""),
            bbox_px=_bbox(data.get("bbox_px")),
            positive_points=_point_list(data.get("positive_points")),
            negative_points=_point_list(data.get("negative_points")),
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
            preview_path=str(data.get("preview_path") or ""),
        )


def mask_bbox(mask: Image.Image) -> dict | None:
    arr = np.asarray(mask.convert("L"))
    ys, xs = np.nonzero(arr)
    if len(xs) == 0:
        return None
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max())
    y1 = int(ys.max())
    return {"x": x0, "y": y0, "width": x1 - x0 + 1, "height": y1 - y0 + 1}


def apply_mask_to_alpha(image: Image.Image, mask: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    m = mask.convert("L")
    if m.size != rgba.size:
        m = m.resize(rgba.size, Image.Resampling.NEAREST)
    arr = np.asarray(rgba).copy()
    mask_arr = np.asarray(m, dtype=np.uint16)
    alpha = arr[:, :, 3].astype(np.uint16)
    arr[:, :, 3] = ((alpha * mask_arr) // 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")
