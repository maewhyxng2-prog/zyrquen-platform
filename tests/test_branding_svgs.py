import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


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


class TestBrandingSvgs(unittest.TestCase):
    def test_brand_assets_are_safe_well_formed_vector_svg(self):
        for filename in SVG_FILES:
            with self.subTest(filename=filename):
                root = ET.parse(ASSET_DIR / filename).getroot()
                self.assertEqual(root.tag, f"{SVG_NAMESPACE}svg")
                self.assertTrue(root.get("viewBox"))
                self.assertTrue(root.get("width") and root.get("height"))

                for element in root.iter():
                    name = element.tag.removeprefix(SVG_NAMESPACE)
                    self.assertIn(name, ALLOWED_ELEMENTS)
                    for attribute, value in element.attrib.items():
                        self.assertFalse(attribute.lower().startswith("on"))
                        if attribute.rsplit("}", 1)[-1].lower() == "href":
                            self.assertTrue(value.startswith("#"))
                        self.assertIsNone(re.search(r"url\(\s*(?!#)", value, re.IGNORECASE))

                styles = "\n".join(
                    element.text or ""
                    for element in root.iter(f"{SVG_NAMESPACE}style")
                )
                self.assertIsNone(re.search(r"@import|javascript:|https?://", styles, re.IGNORECASE))

    def test_animated_brand_assets_honor_reduced_motion(self):
        for filename in ANIMATED_FILES:
            with self.subTest(filename=filename):
                root = ET.parse(ASSET_DIR / filename).getroot()
                styles = "\n".join(
                    element.text or ""
                    for element in root.iter(f"{SVG_NAMESPACE}style")
                )
                self.assertIn("@keyframes", styles)
                self.assertIn("prefers-reduced-motion: reduce", styles)
                self.assertIn("animation: none !important", styles)

    def test_monochrome_assets_follow_system_and_forced_colors(self):
        for filename in SVG_FILES:
            if not filename.endswith("-mono.svg"):
                continue
            with self.subTest(filename=filename):
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
                self.assertIn("currentColor", styles + values)
                self.assertIn("prefers-color-scheme: dark", styles)
                self.assertIn("forced-colors: active", styles)


if __name__ == "__main__":
    unittest.main()
