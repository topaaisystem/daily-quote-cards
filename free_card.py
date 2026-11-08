"""1536x1536 명언 카드 합성(Pillow, 로컬·무료): 배경 명화 + 영어/한국어 명언 + 명언자 초상·이름."""
import io
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

SIZE = 1536
FONTS = Path(__file__).resolve().parent / 'fonts'   # 프로젝트에 포함된 OFL 글꼴(노트북·GitHub 서버 동일)
GOLD, WHITE, SOFT = '#f2d79b', '#ffffff', '#d9d4c7'
# 기존 이름 -> (파일, 크기 보정). Crimson Text는 같은 포인트에서 작게 보여 1.18배.
FACES = {
    'georgia.ttf': ('CrimsonText-Regular.ttf', 1.18),
    'georgiai.ttf': ('CrimsonText-Italic.ttf', 1.18),
    'georgiaz.ttf': ('CrimsonText-SemiBoldItalic.ttf', 1.18),
    'malgun.ttf': ('NanumGothic-Regular.ttf', 0.95),
    'malgunbd.ttf': ('NanumGothic-Bold.ttf', 0.95),
}


def font(name, size):
    file, scale = FACES[name]
    return ImageFont.truetype(str(FONTS / file), round(size * scale))


def wrap(draw, text, fnt, width):
    """공백 기준 줄바꿈(영어), 공백 없는 긴 단어는 글자 단위. 한국어도 어절 단위로 처리."""
    lines, cur = [], ''
    for word in text.split():
        test = (cur + ' ' + word).strip()
        if draw.textlength(test, font=fnt) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, name, sizes, width, max_height, spacing):
    for size in sizes:
        fnt = font(name, size)
        lines = wrap(draw, text, fnt, width)
        if len(lines) * size * spacing <= max_height:
            return fnt, lines, size
    fnt = font(name, sizes[-1])
    return fnt, wrap(draw, text, fnt, width), sizes[-1]


def cover(image, side):
    image = image.convert('RGB')
    mx, my = int(image.width * 0.07), int(image.height * 0.07)   # 스캔 가장자리(액자·여백) 제거
    image = image.crop((mx, my, image.width - mx, image.height - my))
    scale = side / min(image.size)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def circle_portrait(data, diameter):
    img = Image.open(io.BytesIO(data)).convert('RGB')
    side = min(img.size)
    top = int((img.height - side) * 0.12)          # 얼굴이 위쪽에 있으므로 위쪽 기준 크롭
    img = img.crop(((img.width - side) // 2, top, (img.width + side) // 2, top + side))
    img = img.resize((diameter, diameter), Image.Resampling.LANCZOS)
    big = Image.new('L', (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    mask = big.resize((diameter, diameter), Image.Resampling.LANCZOS)
    return img, mask


def render(record, portrait_bytes, background_bytes, out_path):
    q = record['quote']
    person, port, bg = record['person'], record['portrait'], record['background']
    canvas = ImageEnhance.Brightness(cover(Image.open(io.BytesIO(background_bytes)), SIZE)).enhance(0.55)
    shade = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(SIZE):                              # 아래로 갈수록 어두운 그라데이션
        sd.line((0, y, SIZE, y), fill=(8, 10, 18, int(70 + 130 * (y / SIZE) ** 1.6)))
    canvas = Image.alpha_composite(canvas.convert('RGBA'), shade)
    draw = ImageDraw.Draw(canvas)

    draw.text((96, 84), record['theme_label'].upper(), font=font('georgia.ttf', 30), fill=GOLD)
    draw.text((SIZE - 96, 84), record['day'].replace('-', '.'), font=font('georgia.ttf', 30), fill=SOFT, anchor='ra')
    draw.line((96, 138, SIZE - 96, 138), fill=GOLD, width=2)
    draw.text((96, 150), '\u201c', font=font('georgiaz.ttf', 190), fill=GOLD)

    width = SIZE - 2 * 110
    en_font, en_lines, en_size = fit(draw, q['en'], 'georgiai.ttf', [66, 60, 54, 48, 44, 40], width, 380, 1.32)
    y = 330
    for line in en_lines:
        draw.text((110, y), line, font=en_font, fill=WHITE)
        y += en_size * 1.32
    y += 28
    draw.line((110, y, 230, y), fill=GOLD, width=3)
    y += 34
    ko_font, ko_lines, ko_size = fit(draw, q['ko'], 'malgunbd.ttf', [46, 42, 38, 34, 30], width, 1060 - y, 1.45)
    for line in ko_lines:
        draw.text((110, y), line, font=ko_font, fill=GOLD)
        y += ko_size * 1.45

    panel = Image.new('RGBA', (SIZE, 330), (6, 8, 16, 170))
    canvas.alpha_composite(panel, (0, 1116))
    draw = ImageDraw.Draw(canvas)
    pic, mask = circle_portrait(portrait_bytes, 250)
    canvas.paste(pic, (96, 1156), mask)
    draw.ellipse((92, 1152, 350, 1410), outline=GOLD, width=4)

    tx = 392
    name_size = 54
    name_font = font('georgiaz.ttf', name_size)
    while draw.textlength(person['name'], font=name_font) > SIZE - tx - 96 and name_size > 28:
        name_size -= 2                                 # font()가 크기를 보정하므로 기준 크기를 따로 추적
        name_font = font('georgiaz.ttf', name_size)
    draw.text((tx, 1160), person['name'], font=name_font, fill=WHITE)
    if person.get('ko'):
        draw.text((tx, 1246), person['ko'], font=font('malgunbd.ttf', 36), fill=GOLD)
    desc_font = font('malgun.ttf', 25)
    for i, line in enumerate(wrap(draw, person.get('desc', ''), desc_font, SIZE - tx - 96)[:2]):
        draw.text((tx, 1296 + i * 32), line, font=desc_font, fill=SOFT)
    src_font = font('malgun.ttf', 22)
    source = q['source']
    if len(source) > 120:                              # 단어 중간에서 끊지 않고 말줄임
        source = source[:120].rsplit(' ', 1)[0].rstrip(',;:') + '…'
    for i, line in enumerate(wrap(draw, 'Source: ' + source, src_font, SIZE - tx - 96)[:2]):
        draw.text((tx, 1356 + i * 28), line, font=src_font, fill=SOFT)

    credit_font = font('malgun.ttf', 18)
    draw.text((96, 1464), f"Quote: Wikiquote (CC BY-SA) \u00b7 Portrait: Wikimedia Commons, {port['license']} \u00b7 한국어: 자동 번역",
              font=credit_font, fill='#a8a498')
    bg_line = f"Background: {re.sub(r'[_]+', ' ', bg['title'])}, {bg['license']}"
    while draw.textlength(bg_line, font=credit_font) > SIZE - 192:
        bg_line = bg_line[:-5] + '\u2026'
    draw.text((96, 1492), bg_line, font=credit_font, fill='#a8a498')
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert('RGB').save(out_path, 'JPEG', quality=93, subsampling=0)
    return out_path
