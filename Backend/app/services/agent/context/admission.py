"""MapContext and Client Context Admission Guard.

Provides deterministic admission and sanitization for client-supplied map_context,
enforcing Cesium/OpenLayers authority contracts and defending against semantic injection.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

VALID_DIMENSIONS = {"2d", "3d"}
VALID_CRS = {"EPSG:4326", "EPSG:3857"}
VALID_WEBGIS_TOOLS = {
    "locate_map",
    "set_layer_visibility",
    "import_vector_dataset",
    "set_vector_style",
    "fit_vector_layer",
    "inspect_layer_features",
    "get_feature_geometry",
    "render_geojson_layer",
}
VALID_LAYER_KINDS = {"base", "annotation", "business", "user_vector", "group", "unknown"}
ADCODE_PATTERN = re.compile(r"^\d{2,6}$")
SAFE_TEXT_PATTERN = re.compile(r"^[\w\s\u4e00-\u9fa5\.\-\(\)（）_:,]{1,100}$")


def _is_finite_number(val: Any) -> bool:
    if isinstance(val, (int, float)):
        return not (math.isnan(val) or math.isinf(val))
    return False


def _sanitize_layer_tree_node(node: Any, depth: int = 0) -> dict[str, Any] | None:
    if not isinstance(node, Mapping) or depth > 5:
        return None
    layer_ref = str(node.get("layer_ref") or "").strip()
    if not layer_ref or len(layer_ref) > 100:
        return None

    kind = str(node.get("kind") or "unknown").strip()
    if kind not in VALID_LAYER_KINDS:
        kind = "unknown"

    name = str(node.get("name") or layer_ref).strip()
    if len(name) > 100 or not SAFE_TEXT_PATTERN.match(name):
        name = layer_ref

    sanitized: dict[str, Any] = {
        "layer_ref": layer_ref,
        "name": name,
        "kind": kind,
        "visible": bool(node.get("visible", True)),
        "opacity": float(node.get("opacity", 1.0)) if _is_finite_number(node.get("opacity")) else 1.0,
    }

    parent_ref = node.get("parent_ref")
    if parent_ref is not None:
        p_str = str(parent_ref).strip()
        if p_str and len(p_str) <= 100:
            sanitized["parent_ref"] = p_str

    z_index = node.get("z_index")
    if _is_finite_number(z_index):
        sanitized["z_index"] = int(z_index)

    children_raw = node.get("children")
    if isinstance(children_raw, (list, tuple)):
        clean_children = []
        for child in children_raw[:50]:
            clean_child = _sanitize_layer_tree_node(child, depth + 1)
            if clean_child is not None:
                clean_children.append(clean_child)
        sanitized["children"] = clean_children

    return sanitized


def admit_map_context(
    raw: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate and sanitize client-provided map_context.

    Returns:
        (admitted_map_context, None) if admission succeeds.
        (None, rejection_hint) if admission is rejected.
    """
    if raw is None:
        return None, None

    if not isinstance(raw, Mapping):
        return None, {
            "admission_status": "rejected",
            "reason": "map_context must be a JSON object",
        }

    # 1. Schema version
    schema_version = raw.get("schema_version")
    if schema_version != 2:
        return None, {
            "admission_status": "rejected",
            "reason": f"unsupported schema_version: {schema_version}, expected 2",
        }

    # 2. Dimension
    dimension = raw.get("dimension")
    if dimension not in VALID_DIMENSIONS:
        return None, {
            "admission_status": "rejected",
            "reason": f"invalid dimension: {dimension}, expected '2d' or '3d'",
        }

    # 3. Revision & Ready
    revision = raw.get("revision", 0)
    if not isinstance(revision, int) or revision < 0:
        revision = 0
    ready = bool(raw.get("ready", True))

    # 4. Supported tools
    raw_tools = raw.get("supported_tools")
    if not isinstance(raw_tools, (list, tuple)):
        clean_tools = ["locate_map", "set_layer_visibility"]
    else:
        clean_tools = [
            str(t) for t in raw_tools if str(t) in VALID_WEBGIS_TOOLS
        ]

    # 5. Viewport validation
    viewport_raw = raw.get("viewport")
    clean_viewport: dict[str, Any] | None = None
    if viewport_raw is not None:
        if not isinstance(viewport_raw, Mapping):
            return None, {
                "admission_status": "rejected",
                "reason": "viewport must be an object",
            }
        center_raw = viewport_raw.get("center")
        if not (
            isinstance(center_raw, (list, tuple))
            and len(center_raw) == 2
            and _is_finite_number(center_raw[0])
            and _is_finite_number(center_raw[1])
        ):
            return None, {
                "admission_status": "rejected",
                "reason": "viewport center must be a [lon, lat] coordinate pair",
            }
        lon, lat = float(center_raw[0]), float(center_raw[1])
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return None, {
                "admission_status": "rejected",
                "reason": f"viewport center coordinates out of bounds: lon={lon}, lat={lat}",
            }

        zoom_raw = viewport_raw.get("zoom")
        if not _is_finite_number(zoom_raw):
            return None, {
                "admission_status": "rejected",
                "reason": "viewport zoom must be a valid number",
            }
        zoom = float(zoom_raw)
        if not (0.0 <= zoom <= 28.0):
            return None, {
                "admission_status": "rejected",
                "reason": f"viewport zoom out of range [0, 28]: {zoom}",
            }

        crs_raw = str(viewport_raw.get("crs") or "EPSG:4326").strip().upper()
        if crs_raw not in VALID_CRS:
            crs_raw = "EPSG:4326"

        clean_viewport = {
            "center": [lon, lat],
            "zoom": zoom,
            "crs": crs_raw,
        }

    # 6. Active region validation
    region_raw = raw.get("active_region")
    clean_region: dict[str, str] | None = None
    if region_raw is not None:
        if isinstance(region_raw, Mapping):
            adcode = str(region_raw.get("adcode") or "").strip()
            name = str(region_raw.get("name") or "").strip()
            if (
                ADCODE_PATTERN.match(adcode)
                and name
                and len(name) <= 50
                and SAFE_TEXT_PATTERN.match(name)
            ):
                clean_region = {"adcode": adcode, "name": name}

    # 7. Layer tree validation
    layer_tree_raw = raw.get("layer_tree")
    clean_tree: list[dict[str, Any]] = []
    if isinstance(layer_tree_raw, (list, tuple)):
        for node in layer_tree_raw[:100]:
            clean_node = _sanitize_layer_tree_node(node)
            if clean_node is not None:
                clean_tree.append(clean_node)

    # 8. User layers validation
    user_layers_raw = raw.get("user_layers")
    clean_users: list[dict[str, Any]] = []
    if isinstance(user_layers_raw, (list, tuple)):
        for u in user_layers_raw[:50]:
            if not isinstance(u, Mapping):
                continue
            lref = str(u.get("layer_ref") or "").strip()
            if not lref or len(lref) > 100:
                continue
            uname = str(u.get("name") or lref).strip()
            if len(uname) > 100 or not SAFE_TEXT_PATTERN.match(uname):
                uname = lref
            fcount = u.get("feature_count", 0)
            if not isinstance(fcount, int) or fcount < 0:
                fcount = 0
            gtypes = [
                str(gt) for gt in (u.get("geometry_types") or ())
                if isinstance(gt, str) and len(gt) <= 30
            ]
            frefs = [
                str(fr) for fr in (u.get("feature_refs") or ())
                if isinstance(fr, str) and len(fr) <= 100
            ][:200]
            clean_users.append({
                "layer_ref": lref,
                "name": uname,
                "geometry_types": gtypes,
                "feature_count": fcount,
                "feature_refs": frefs,
                "visible": bool(u.get("visible", True)),
                "style": dict(u.get("style")) if isinstance(u.get("style"), Mapping) else {},
            })

    # 9. Available files validation
    avail_files_raw = raw.get("available_files")
    clean_files: list[dict[str, Any]] = []
    if isinstance(avail_files_raw, (list, tuple)):
        for f in avail_files_raw[:50]:
            if not isinstance(f, Mapping):
                continue
            fref = str(f.get("file_ref") or "").strip()
            if not fref or len(fref) > 100:
                continue
            fname = str(f.get("name") or fref).strip()
            if len(fname) > 100 or not SAFE_TEXT_PATTERN.match(fname):
                fname = fref
            fmt = str(f.get("format") or "shapefile").strip().lower()
            if fmt not in {"shapefile", "geojson"}:
                fmt = "shapefile"
            parts = [
                str(p) for p in (f.get("parts") or ())
                if isinstance(p, str) and len(p) <= 50
            ][:20]
            clean_files.append({
                "file_ref": fref,
                "name": fname,
                "format": fmt,
                "parts": parts,
            })

    admitted: dict[str, Any] = {
        "schema_version": 2,
        "revision": revision,
        "dimension": dimension,
        "ready": ready,
        "supported_tools": clean_tools,
        "viewport": clean_viewport,
        "active_region": clean_region,
        "layer_tree": clean_tree,
        "user_layers": clean_users,
        "available_files": clean_files,
    }
    return admitted, None
