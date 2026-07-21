"""Create or annotate Feishu guide screenshots from the JSON manifest.

Pillow is intentionally an optional documentation dependency:
    python -m pip install Pillow
    python scripts/annotate_feishu_guide.py --placeholders
    python scripts/annotate_feishu_guide.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as exc:  # pragma: no cover - depends on contributor tooling
    raise SystemExit("Pillow is required for screenshot processing: python -m pip install Pillow") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs" / "feishu-guide" / "screenshot-manifest.json"
DEFAULT_RAW = ROOT / "docs" / "feishu-guide" / "raw"
DEFAULT_OUTPUT = ROOT / "src" / "jobpicky" / "web" / "static" / "images" / "feishu-guide"
RED = (218, 58, 58, 255)


def font(size: int, *, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def pixels(box, size):
    width, height = size
    x, y, w, h = box
    return (round(x * width), round(y * height), round((x + w) * width), round((y + h) * height))


def placeholder(item: dict, size=(1440, 900)) -> Image.Image:
    image = Image.new("RGBA", size, "#f3f5f8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((44, 42, size[0] - 44, size[1] - 42), 24, fill="#ffffff", outline="#d8dee8", width=2)
    draw.rectangle((45, 43, size[0] - 45, 118), fill="#f8fafc")
    draw.text((78, 66), "飞书操作截图占位图", font=font(25, bold=True), fill="#222b38")
    draw.text((size[0] - 340, 69), f"向导第 {item['wizardStep']} 步", font=font(20), fill="#607087")
    draw.rounded_rectangle((78, 158, 310, size[1] - 88), 16, fill="#f1f4f8")
    for index in range(5):
        y = 205 + index * 72
        draw.rounded_rectangle((105, y, 280, y + 38), 8, fill="#dde4ed" if index else "#d9e7fb")
    draw.text((358, 170), item["pageDescription"], font=font(31, bold=True), fill="#1f2733")
    draw.text((358, 228), "正式截图获取前用于本地布局与交互验收", font=font(19), fill="#687487")
    for index, label in enumerate(item["requiredVisibleElements"]):
        y = 315 + index * 86
        draw.rounded_rectangle((358, y, 1110, y + 56), 10, fill="#f5f7fa", outline="#dce2ea")
        draw.text((385, y + 14), label, font=font(19), fill="#485465")
    draw.text((358, size[1] - 112), "此图不包含真实企业、账号或应用凭据", font=font(17), fill="#8a6470")
    return image


def redact(image: Image.Image, item: dict) -> None:
    for redaction in item.get("redactions", []):
        box = pixels(redaction["box"], image.size)
        if redaction.get("mode") == "blur":
            blurred = image.crop(box).filter(ImageFilter.GaussianBlur(18))
            image.paste(blurred, box)
        else:
            ImageDraw.Draw(image).rounded_rectangle(box, 5, fill="#202733")


def annotate(image: Image.Image, item: dict) -> None:
    draw = ImageDraw.Draw(image)
    for annotation in item.get("annotations", []):
        box = pixels(annotation["box"], image.size)
        draw.rounded_rectangle(box, 14, outline=RED, width=4)
        number = annotation.get("number")
        if number is not None:
            cx, cy = box[0] + 8, box[1] + 8
            draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=RED)
            text = str(number)
            bounds = draw.textbbox((0, 0), text, font=font(21, bold=True))
            draw.text((cx - (bounds[2] - bounds[0]) / 2, cy - (bounds[3] - bounds[1]) / 2 - 2), text, font=font(21, bold=True), fill="white")
        if arrow := annotation.get("arrow"):
            start = (round(arrow[0][0] * image.width), round(arrow[0][1] * image.height))
            end = (round(arrow[1][0] * image.width), round(arrow[1][1] * image.height))
            draw.line((start, end), fill=RED, width=4)
            draw.ellipse((end[0] - 6, end[1] - 6, end[0] + 6, end[1] + 6), fill=RED)


def process(item: dict, source_dir: Path, output_dir: Path, placeholders: bool) -> str:
    source = source_dir / item["file"]
    if source.exists():
        image = Image.open(source).convert("RGBA")
    elif placeholders:
        image = placeholder(item)
    else:
        return f"missing: {source}"
    crop = item.get("crop")
    if crop:
        image = image.crop(pixels(crop, image.size))
    redact(image, item)
    annotate(image, item)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / item["file"]
    image.convert("RGB").save(destination, optimize=True)
    return f"wrote: {destination}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--placeholders", action="store_true", help="generate safe local placeholders when raw files are absent")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    for item in manifest:
        print(process(item, args.source_dir, args.output_dir, args.placeholders))


if __name__ == "__main__":
    main()
