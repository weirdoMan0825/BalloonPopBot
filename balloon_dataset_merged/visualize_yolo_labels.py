#!/usr/bin/env python3
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_CLASS_NAMES = [
    "pink_balloon",
    "red_balloon",
    "green_balloon",
    "blue_balloon",
    "orange_balloon",
    "purple_balloon",
    "yellow_balloon",
]
COLORS = [
    (255, 80, 180),
    (235, 40, 45),
    (25, 170, 75),
    (40, 110, 230),
    (255, 145, 30),
    (155, 80, 220),
    (245, 215, 30),
]


def iter_images(path: Path):
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def load_class_names(dataset_root: Path):
    candidates = [
        dataset_root / "labels" / "train" / "classes.txt",
        dataset_root / "labels" / "classes.txt",
        dataset_root / "classes.txt",
    ]
    for path in candidates:
        if path.exists():
            names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if names:
                return names
    return DEFAULT_CLASS_NAMES


def parse_label(label_path: Path, class_count: int):
    boxes = []
    errors = []
    for line_no, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) != 5:
            errors.append(f"line {line_no}: expected 5 values")
            continue
        try:
            cls = int(float(parts[0]))
            x, y, w, h = [float(v) for v in parts[1:]]
        except ValueError:
            errors.append(f"line {line_no}: non-numeric value")
            continue
        if cls < 0 or cls >= class_count:
            errors.append(f"line {line_no}: class id {cls} out of range")
        if not all(0.0 <= v <= 1.0 for v in (x, y, w, h)):
            errors.append(f"line {line_no}: bbox outside 0..1")
        if w <= 0 or h <= 0:
            errors.append(f"line {line_no}: bbox width/height <= 0")
        boxes.append((cls, x, y, w, h))
    return boxes, errors


def draw_label(image_path: Path, label_path: Path, output_path: Path, class_names):
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    boxes, errors = parse_label(label_path, len(class_names))

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for cls, x, y, w, h in boxes:
        color = COLORS[cls % len(COLORS)]
        x1 = int((x - w / 2) * width)
        y1 = int((y - h / 2) * height)
        x2 = int((x + w / 2) * width)
        y2 = int((y + h / 2) * height)
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(0, min(width - 1, x2))
        y2 = max(0, min(height - 1, y2))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        label = class_names[cls] if 0 <= cls < len(class_names) else f"class_{cls}"
        text_bbox = draw.textbbox((x1, y1), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        text_y1 = max(0, y1 - text_h - 6)
        draw.rectangle((x1, text_y1, x1 + text_w + 8, text_y1 + text_h + 6), fill=color)
        draw.text((x1 + 4, text_y1 + 3), label, fill=(0, 0, 0), font=font)

    if errors:
        draw.text((8, 8), "LABEL ERROR: " + "; ".join(errors[:2]), fill=(255, 0, 0), font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=92)
    return errors


def main():
    parser = argparse.ArgumentParser(description="Draw YOLO labels on images for visual checking.")
    parser.add_argument("--dataset", required=True, type=Path, help="YOLO dataset root.")
    parser.add_argument("--split", default="train")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--samples", type=int, default=120, help="0 means all images.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    image_dir = dataset / "images" / args.split
    label_dir = dataset / "labels" / args.split
    output_dir = args.output or (dataset / "visual_check")

    class_names = load_class_names(dataset)
    images = iter_images(image_dir)
    rng = random.Random(args.seed)
    selected = images if args.samples <= 0 or args.samples >= len(images) else rng.sample(images, args.samples)

    missing_labels = []
    bad_labels = []
    for image_path in sorted(selected):
        label_path = label_dir / f"{image_path.stem}.txt"
        if not label_path.exists():
            missing_labels.append(str(image_path))
            continue
        errors = draw_label(image_path, label_path, output_dir / image_path.name, class_names)
        if errors:
            bad_labels.append((str(label_path), "; ".join(errors)))

    print(f"dataset={dataset}")
    print(f"images_found={len(images)}")
    print(f"visualized={len(selected) - len(missing_labels)}")
    print(f"missing_labels={len(missing_labels)}")
    print(f"bad_labels={len(bad_labels)}")
    print(f"output={output_dir}")


if __name__ == "__main__":
    main()

