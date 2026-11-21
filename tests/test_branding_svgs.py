import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ASSET_DIR = Path(__file__).parents[1] / "apps" / "web" / "public"
SVG_FILES = (
    "zyrquen-logo.svg",
    "zyrquen-icon.svg",
    "zyrquen-wordmark.svg",
    "zyrquen-logo-mono.svg",
    "zyrquen-icon-mono.svg",
    "zyrquen-wordmark-mono.svg",
)
ANIMATED_FILES = (
    "zyrquen-logo.svg",
    "zyrquen-icon.svg",
    "zyrquen-logo-mono.svg",
    "zyrquen-icon-mono.svg",
)
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
ALLOWED_ELEMENTS = {
    "circle",
    "defs",
    "ellipse",
    "filter",
    "feGaussianBlur",
    "feMerge",
    "feMergeNode",
    "g",
    "linearGradient",
    "path",
    "radialGradient",
    "stop",
    "style",
    "svg",
    "text",
    "title",
}


@pytest.mark.parametrize("filename", SVG_FILES)
def test_brand_assets_are_safe_well_formed_vector_svg(filename):
    root = ET.parse(ASSET_DIR / filename).getroot()
    assert root.tag == f"{SVG_NAMESPACE}svg"
    assert root.get("viewBox")
    assert root.get("width") and root.get("height")

    for element in root.iter():
        name = element.tag.removeprefix(SVG_NAMESPACE)
        assert name in ALLOWED_ELEMENTS
        for attribute, value in element.attrib.items():
            assert not attribute.lower().startswith("on")
            if attribute.rsplit("}", 1)[-1].lower() == "href":
                assert value.startswith("#")
            assert not re.search(r"url\(\s*(?!#)", value, re.IGNORECASE)

    styles = "\n".join(
        element.text or ""
        for element in root.iter(f"{SVG_NAMESPACE}style")
    )
    assert not re.search(r"@import|javascript:|https?://", styles, re.IGNORECASE)


@pytest.mark.parametrize("filename", ANIMATED_FILES)
def test_animated_brand_assets_honor_reduced_motion(filename):
    root = ET.parse(ASSET_DIR / filename).getroot()
    styles = "\n".join(
        element.text or ""
        for element in root.iter(f"{SVG_NAMESPACE}style")
    )
    assert "@keyframes" in styles
    assert "prefers-reduced-motion: reduce" in styles
    assert "animation: none !important" in styles


def test_monochrome_assets_follow_system_and_forced_colors():
    for filename in SVG_FILES:
        if not filename.endswith("-mono.svg"):
            continue
        root = ET.parse(ASSET_DIR / filename).getroot()
        styles = "\n".join(
            element.text or ""
            for element in root.iter(f"{SVG_NAMESPACE}style")
        )
        values = " ".join(
            value
            for element in root.iter()
            for value in element.attrib.values()
        )
        assert "currentColor" in styles + values
        assert "prefers-color-scheme: dark" in styles
        assert "forced-colors: active" in styles
