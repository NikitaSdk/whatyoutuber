"""Текст слайда и, если включено, формула. Кадр после этого удаляется."""

import threading

_LATEX = None
_LATEX_LOCK = threading.Lock()


def _latex_reader():
    global _LATEX
    with _LATEX_LOCK:
        if _LATEX is None:
            from pix2tex.cli import LatexOCR
            _LATEX = LatexOCR()
        return _LATEX


def prepare_image(img):
    from PIL import Image

    gray = img.convert("L")
    histogram = gray.histogram()
    total = sum(histogram) or 1
    brightness = sum(index * count for index, count in enumerate(histogram)) / total
    if brightness < 100:
        gray = gray.point(lambda value: 255 - value)
    return gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)


def read_text(img) -> tuple[str, float]:
    import pytesseract

    data = pytesseract.image_to_data(img, lang="rus+eng", output_type=pytesseract.Output.DICT)
    lines = {}
    confs = []
    for index, word in enumerate(data.get("text") or []):
        try:
            conf = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        if word.strip() and conf >= 60:
            key = (data["block_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(word)
            confs.append(conf)
    text = "\n".join(" ".join(words) for _key, words in sorted(lines.items()))
    return text, (sum(confs) / len(confs) if confs else 0)


def read_formulas(img) -> list:
    try:
        reader = _latex_reader()
    except Exception:
        return []
    import pytesseract

    data = pytesseract.image_to_data(img, lang="rus+eng", output_type=pytesseract.Output.DICT)
    found = []
    boxes = {}
    for index, word in enumerate(data.get("text") or []):
        try:
            conf = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        marks = sum(1 for char in word if char in "=+-−∫∑^/")
        if conf < 40 and marks:
            key = (data["block_num"][index], data["line_num"][index])
            left, top, width, height = data["left"][index], data["top"][index], data["width"][index], data["height"][index]
            box = boxes.get(key)
            if box is None:
                boxes[key] = [left, top, left + width, top + height]
            else:
                box[0] = min(box[0], left)
                box[1] = min(box[1], top)
                box[2] = max(box[2], left + width)
                box[3] = max(box[3], top + height)
    for left, top, right, bottom in boxes.values():
        crop = img.crop((max(0, left - 8), max(0, top - 8), right + 8, bottom + 8))
        latex = str(reader(crop) or "").strip()
        if latex:
            found.append(latex)
    return found


def read_frame(img, formulas: bool = False) -> dict:
    prepared = prepare_image(img)
    text, conf = read_text(prepared)
    latex = read_formulas(prepared) if formulas else []
    return {"text": text, "latex": latex, "conf": round(conf)}
