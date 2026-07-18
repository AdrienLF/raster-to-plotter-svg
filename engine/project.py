"""Project model + on-disk workspace.

A project bundles the source image, the current Drawing Area, Drawing Set, the
selected PFM + params, and an ordered list of saved Versions. Everything lives
under ``~/.plotterforge/projects/<id>/``.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from .composition import Composition
from .canvas import DrawingArea
from .geometry import Drawing
from .pens import DrawingSet
from .regions import Region, apply_mask_to_alpha
from .versioning import Version, render_thumbnail

WORKSPACE = Path.home() / ".plotterforge"
_LEGACY_WORKSPACE = Path.home() / ".plotter_studio"
PROJECTS_DIR = WORKSPACE / "projects"


def _migrate_legacy_workspace() -> None:
    # One-time move of pre-rename data (~/.plotter_studio) to the new location.
    if _LEGACY_WORKSPACE.is_dir() and not WORKSPACE.exists():
        try:
            _LEGACY_WORKSPACE.rename(WORKSPACE)
        except OSError:
            pass  # e.g. cross-device or permission issue; fall back to a fresh workspace


_migrate_legacy_workspace()


class VersionSnapshotError(ValueError):
    pass


class Project:
    def __init__(self, pid: str):
        self.id = pid
        self.dir = PROJECTS_DIR / pid
        self.name = "Untitled"
        self.image_name = ""
        self.area = DrawingArea()
        self.drawing_set = DrawingSet()
        self.composition = Composition()
        self.regions: list[Region] = []
        self.selected_region_id: str | None = None
        self.field_masks: list[dict] = []   # painted grayscale field masks
        self.pfm_id = "voronoi_stippling"
        self.params: dict[str, Any] = {}
        self.versions: list[Version] = []

    # ── paths ────────────────────────────────────────────────────────────────
    @property
    def versions_dir(self) -> Path:
        return self.dir / "versions"

    @property
    def layers_dir(self) -> Path:
        return self.dir / "layers"

    @property
    def regions_dir(self) -> Path:
        return self.dir / "regions"

    @property
    def image_path(self) -> Path | None:
        return self.dir / self.image_name if self.image_name else None

    # ── persistence ──────────────────────────────────────────────────────────
    def ensure_dirs(self) -> None:
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.layers_dir.mkdir(parents=True, exist_ok=True)
        self.regions_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "image_name": self.image_name,
            "area": self.area.to_dict(),
            "drawing_set": self.drawing_set.to_dict(),
            "composition": self.composition.to_dict(),
            "regions": [r.to_dict() for r in self.regions],
            "selected_region_id": self.selected_region_id,
            "field_masks": self.field_masks,
            "pfm_id": self.pfm_id,
            "params": self.params,
            "versions": [v.to_dict() for v in self.versions],
        }

    def save(self) -> None:
        self.ensure_dirs()
        (self.dir / "project.json").write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, pid: str) -> "Project":
        p = cls(pid)
        f = p.dir / "project.json"
        if f.exists():
            d = json.loads(f.read_text())
            p.name = d.get("name", "Untitled")
            p.image_name = d.get("image_name", "")
            p.area = DrawingArea.from_dict(d.get("area"))
            p.drawing_set = DrawingSet.from_dict(d.get("drawing_set"))
            p.composition = Composition.from_dict(d.get("composition"))
            p.regions = [Region.from_dict(r) for r in d.get("regions", [])]
            p.selected_region_id = d.get("selected_region_id")
            if p.selected_region_id and not p.get_region(p.selected_region_id):
                p.selected_region_id = None
            p.field_masks = [dict(m) for m in d.get("field_masks", [])]
            for layer in p.composition.layers:
                layer_path = p.dir / layer.svg_path if layer.svg_path else None
                if layer_path and layer_path.exists():
                    layer.svg = layer_path.read_text()
            p.pfm_id = d.get("pfm_id", "voronoi_stippling")
            p.params = d.get("params", {})
            p.versions = [Version.from_dict(v) for v in d.get("versions", [])]
        return p

    def save_composition_layers(self) -> None:
        self.ensure_dirs()
        active_ids = {layer.id for layer in self.composition.layers}
        for layer in self.composition.layers:
            if not layer.svg_path:
                layer.svg_path = f"layers/{layer.id}.svg"
            (self.dir / layer.svg_path).write_text(layer.svg)
        # Remove files (SVG bodies and raster-layer images) of deleted layers.
        # A duplicated raster layer shares its original's image file, so keep
        # any file still referenced by a live layer's image_path.
        referenced = {
            Path(layer.image_path).name
            for layer in self.composition.layers
            if getattr(layer, "image_path", "")
        }
        for path in self.layers_dir.glob("*.*"):
            if path.stem not in active_ids and path.name not in referenced:
                path.unlink()
        self.save()

    # ── regions ─────────────────────────────────────────────────────────────
    def get_region(self, region_id: str | None) -> Region | None:
        if not region_id:
            return None
        return next((r for r in self.regions if r.id == region_id), None)

    def add_region(
        self,
        name: str,
        mask,
        positive_points: list[dict] | None = None,
        negative_points: list[dict] | None = None,
        bbox_px: dict | None = None,
    ) -> Region:
        self.ensure_dirs()
        rid = uuid.uuid4().hex[:10]
        mask_path = f"regions/{rid}.png"
        (self.dir / mask_path).parent.mkdir(parents=True, exist_ok=True)
        mask.convert("L").save(self.dir / mask_path)
        now = time.time()
        region = Region(
            id=rid,
            name=name or "Region",
            mask_path=mask_path,
            bbox_px=bbox_px,
            positive_points=list(positive_points or []),
            negative_points=list(negative_points or []),
            created_at=now,
            updated_at=now,
        )
        self.regions.append(region)
        self.selected_region_id = region.id
        self.save()
        return region

    def update_region(self, region_id: str, **changes) -> Region | None:
        region = self.get_region(region_id)
        if region is None:
            return None
        if "name" in changes:
            region.name = str(changes["name"] or region.name)
        if "mask" in changes:
            mask = changes["mask"]
            mask.convert("L").save(self.dir / region.mask_path)
        if "positive_points" in changes:
            region.positive_points = list(changes["positive_points"] or [])
        if "negative_points" in changes:
            region.negative_points = list(changes["negative_points"] or [])
        if "bbox_px" in changes:
            region.bbox_px = changes["bbox_px"]
        region.updated_at = time.time()
        self.selected_region_id = region.id
        self.save()
        return region

    def delete_region(self, region_id: str) -> bool:
        region = self.get_region(region_id)
        if region is None:
            return False
        self.regions = [r for r in self.regions if r.id != region_id]
        if self.selected_region_id == region_id:
            self.selected_region_id = self.regions[-1].id if self.regions else None
        for rel in (region.mask_path, region.preview_path):
            if rel:
                try:
                    (self.dir / rel).unlink()
                except FileNotFoundError:
                    pass
        self.save()
        return True

    def open_region_mask(self, region_id: str):
        region = self.get_region(region_id)
        if region is None or not region.mask_path:
            return None
        path = self.dir / region.mask_path
        if not path.exists():
            return None
        with Image.open(path) as mask:
            return mask.convert("L")

    def open_region_image(self, region_id: str):
        image = self.open_image()
        mask = self.open_region_mask(region_id)
        if image is None or mask is None:
            return None
        return apply_mask_to_alpha(image, mask)

    # ── painted field masks (grayscale, drive spatial parameter fields) ──────
    def get_field_mask(self, fid: str | None) -> dict | None:
        if not fid:
            return None
        return next((m for m in self.field_masks if m.get("id") == fid), None)

    def add_field_mask(self, name: str, image) -> dict:
        self.ensure_dirs()
        fid = f"fm_{uuid.uuid4().hex[:8]}"
        rel = f"fields/{fid}.png"
        (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
        image.convert("L").save(self.dir / rel)
        mask = {"id": fid, "name": str(name or "Field mask"), "path": rel}
        self.field_masks.append(mask)
        self.save()
        return mask

    def open_field_mask(self, fid: str | None):
        mask = self.get_field_mask(fid)
        if mask is None:
            return None
        path = self.dir / mask["path"]
        if not path.exists():
            return None
        with Image.open(path) as img:
            return img.convert("L")

    def delete_field_mask(self, fid: str) -> bool:
        mask = self.get_field_mask(fid)
        if mask is None:
            return False
        self.field_masks = [m for m in self.field_masks if m.get("id") != fid]
        try:
            (self.dir / mask["path"]).unlink()
        except FileNotFoundError:
            pass
        self.save()
        return True

    # ── source image ─────────────────────────────────────────────────────────
    def set_image(self, data: bytes, filename: str) -> None:
        self.ensure_dirs()
        if self.regions:
            for region in self.regions:
                for rel in (region.mask_path, region.preview_path):
                    if rel:
                        try:
                            (self.dir / rel).unlink()
                        except FileNotFoundError:
                            pass
            self.regions = []
            self.selected_region_id = None
        suffix = Path(filename).suffix.lower() or ".png"
        self.image_name = f"source{suffix}"
        (self.dir / self.image_name).write_bytes(data)
        self.save()

    def open_image(self) -> Image.Image | None:
        ip = self.image_path
        if ip and ip.exists():
            with Image.open(ip) as image:
                return image.copy()
        return None

    # ── raster layers ─────────────────────────────────────────────────────────
    def set_layer_image(self, layer, data: bytes, filename: str) -> None:
        """Persist an imported image as a raster layer's own file."""
        self.ensure_dirs()
        suffix = Path(filename).suffix.lower() or ".png"
        layer.image_path = f"layers/{layer.id}{suffix}"
        (self.dir / layer.image_path).write_bytes(data)
        self.save()

    def open_layer_image(self, layer) -> Image.Image | None:
        rel = getattr(layer, "image_path", "")
        path = (self.dir / rel) if rel else None
        if path and path.exists():
            with Image.open(path) as image:
                return image.copy()
        return None

    # ── versions ─────────────────────────────────────────────────────────────
    def add_version(
        self,
        drawing: Drawing | None,
        name: str = "",
        notes: str = "",
        *,
        thumbnail: Image.Image | None = None,
    ) -> Version:
        self.ensure_dirs()
        vid = uuid.uuid4().hex[:8]
        vdir = self.versions_dir / vid
        vdir.mkdir(parents=True, exist_ok=True)
        if drawing is None and thumbnail is None:
            raise ValueError("A drawing or thumbnail is required")
        thumb = thumbnail if thumbnail is not None else render_thumbnail(drawing)
        thumb.save(vdir / "thumb.png")
        composition_snapshot = ""
        if drawing is None:
            composition_snapshot = f"versions/{vid}/composition.json"
            (self.dir / composition_snapshot).write_text(
                json.dumps(self.composition.to_dict(include_svg=True), indent=2),
                encoding="utf-8",
            )
        v = Version(
            id=vid,
            name=name or self.pfm_id.replace("_", " ").title(),
            pfm_id=self.pfm_id,
            params=dict(self.params),
            area=self.area.to_dict(),
            drawing_set=self.drawing_set.to_dict(),
            image_name=self.image_name,
            notes=notes,
            thumbnail=f"versions/{vid}/thumb.png",
            composition_snapshot=composition_snapshot,
        )
        self.versions.insert(0, v)
        self.save()
        return v

    def get_version(self, vid: str) -> Version | None:
        return next((v for v in self.versions if v.id == vid), None)

    def load_version(self, vid: str) -> bool:
        """Restore a version's settings into the project's current state."""
        v = self.get_version(vid)
        if not v:
            return False
        restored_composition = None
        if v.composition_snapshot:
            try:
                snapshot = json.loads(
                    (self.dir / v.composition_snapshot).read_text(encoding="utf-8")
                )
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("layers"), list):
                    raise ValueError("invalid composition snapshot")
                restored_composition = Composition.from_dict(snapshot)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
                raise VersionSnapshotError(
                    "Version snapshot is unavailable or invalid"
                ) from exc

        self.pfm_id = v.pfm_id
        self.params = dict(v.params)
        self.area = DrawingArea.from_dict(v.area)
        self.drawing_set = DrawingSet.from_dict(v.drawing_set)
        if restored_composition is not None:
            self.composition = restored_composition
            self.save_composition_layers()
        else:
            self.save()
        return True

    def delete_version(self, vid: str) -> bool:
        v = self.get_version(vid)
        if not v:
            return False
        self.versions = [x for x in self.versions if x.id != vid]
        shutil.rmtree(self.versions_dir / vid, ignore_errors=True)
        self.save()
        return True

    def reorder_version(self, vid: str, direction: int) -> bool:
        ids = [v.id for v in self.versions]
        if vid not in ids:
            return False
        i = ids.index(vid)
        j = i + (1 if direction > 0 else -1)
        if 0 <= j < len(self.versions):
            self.versions[i], self.versions[j] = self.versions[j], self.versions[i]
            self.save()
            return True
        return False

    def clear_versions(self) -> None:
        for v in self.versions:
            shutil.rmtree(self.versions_dir / v.id, ignore_errors=True)
        self.versions = []
        self.save()


def get_or_create(pid: str = "default") -> Project:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    p = Project.load(pid)
    p.ensure_dirs()
    if not (p.dir / "project.json").exists():
        p.save()
    return p


def list_projects() -> list[dict]:
    """All projects on disk, most-recently-modified first."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for d in PROJECTS_DIR.iterdir():
        manifest = d / "project.json"
        if not (d.is_dir() and manifest.exists()):
            continue
        try:
            name = json.loads(manifest.read_text()).get("name", d.name)
        except Exception:
            name = d.name
        out.append({"id": d.name, "name": name, "mtime": manifest.stat().st_mtime})
    out.sort(key=lambda p: p["mtime"], reverse=True)
    return out


def create_project(name: str = "Untitled") -> Project:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    p = Project(uuid.uuid4().hex[:10])
    p.name = name or "Untitled"
    p.ensure_dirs()
    p.save()
    return p


def delete_project(pid: str) -> None:
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)
