from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts" / "mockups"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend([
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica Neue.ttc",
        ])
    else:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Helvetica Neue.ttc",
        ])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_H1 = load_font(44, bold=True)
FONT_H2 = load_font(28, bold=True)
FONT_BODY = load_font(20, bold=False)
FONT_SMALL = load_font(16, bold=False)
FONT_MONO = load_font(18, bold=False)


def rounded_box(base: Image.Image, xy, radius, fill, outline=None, width=1, shadow=True):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if shadow:
        shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        sx1, sy1, sx2, sy2 = xy
        shadow_draw.rounded_rectangle(
            (sx1 + 10, sy1 + 16, sx2 + 10, sy2 + 16),
            radius=radius,
            fill=(5, 10, 18, 110),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(18))
        overlay = Image.alpha_composite(overlay, shadow_layer)
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    return Image.alpha_composite(base, overlay)


def speech_bubble(base: Image.Image, xy, fill, outline=None):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=28, fill=fill, outline=outline, width=2 if outline else 1)
    tail = [(x2 - 90, y2 - 4), (x2 - 50, y2 - 4), (x2 - 66, y2 + 28)]
    draw.polygon(tail, fill=fill, outline=outline)
    return Image.alpha_composite(base, overlay)


def draw_gradient(size, top, bottom):
    width, height = size
    img = Image.new("RGBA", size, top)
    px = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(width):
            px[x, y] = (r, g, b, 255)
    return img


def add_text(draw, pos, text, font, fill, spacing=6):
    draw.multiline_text(pos, text, font=font, fill=fill, spacing=spacing)


def draw_desktop_background(img):
    draw = ImageDraw.Draw(img)
    width, height = img.size
    for i in range(12):
        x = 90 + i * 150
        draw.line((x, 0, x - 220, height), fill=(255, 255, 255, 18), width=2)
    for i in range(7):
        y = 120 + i * 120
        draw.arc((width - 700, y - 60, width + 120, y + 320), 180, 310, fill=(255, 255, 255, 20), width=2)
    dock = rounded_box(img, (380, height - 118, width - 380, height - 38), 38, (255, 255, 255, 42))
    draw = ImageDraw.Draw(dock)
    for i in range(8):
        x = 470 + i * 120
        draw.rounded_rectangle((x, height - 102, x + 76, height - 50), radius=18, fill=(255, 255, 255, 90))
    return dock


def draw_ghostty_mockup():
    img = draw_gradient((1600, 1000), (16, 37, 58), (5, 15, 28))
    img = draw_desktop_background(img)
    draw = ImageDraw.Draw(img)

    draw.ellipse((1120, 80, 1510, 470), fill=(72, 166, 255, 32))
    draw.ellipse((70, 520, 480, 930), fill=(41, 226, 168, 24))

    add_text(draw, (88, 72), "方案 A  ·  Ghostty 悬浮终端版", FONT_H1, (242, 248, 255))
    add_text(draw, (88, 132), "本质是一个被做成桌面挂件的透明终端，不是异形桌宠。", FONT_BODY, (194, 209, 226))

    term = rounded_box(img, (920, 120, 1510, 840), 28, (14, 18, 24, 188), outline=(120, 160, 190, 110), width=2)
    img = term
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((942, 146, 1488, 188), radius=16, fill=(255, 255, 255, 26))
    draw.ellipse((962, 160, 978, 176), fill=(255, 95, 86))
    draw.ellipse((988, 160, 1004, 176), fill=(255, 189, 46))
    draw.ellipse((1014, 160, 1030, 176), fill=(39, 201, 63))
    add_text(draw, (1060, 154), "vox-code  ·  ghostty float-on-top", FONT_SMALL, (206, 220, 234))

    code_lines = [
        ">>> /team",
        "切换到 Plan-and-Execute 模式",
        "",
        ">>> 帮我分析当前项目架构",
        "",
        "🧠 思考过程:",
        "1. 读取 README 与入口模块",
        "2. 检查 Agent / Tool / Memory 分层",
        "3. 输出 GUI 改造方案",
        "",
        "🤖 回复:",
        "建议拆出 SessionController，",
        "把终端 print 改造成事件流，",
        "再由 GUI 壳接收状态和流式输出。",
        "",
        "📊 Token: 4820 输入 / 912 输出 / 5732 合计"
    ]
    y = 224
    for line in code_lines:
        fill = (187, 236, 198) if line.startswith(">>>") else (211, 223, 234)
        if line.startswith("🤖"):
            fill = (115, 215, 255)
        elif line.startswith("🧠"):
            fill = (255, 204, 112)
        elif line.startswith("📊"):
            fill = (156, 172, 188)
        add_text(draw, (966, y), line, FONT_MONO, fill)
        y += 34

    bubble = speech_bubble(img, (1020, 740, 1458, 880), (245, 250, 255, 238), outline=(200, 214, 225, 255))
    img = bubble
    draw = ImageDraw.Draw(img)
    add_text(draw, (1050, 770), "像一个终端助手常驻右下角。\n适合快速原型、开发者味很强。", FONT_BODY, (20, 33, 48))

    card = rounded_box(img, (86, 230, 660, 670), 34, (255, 255, 255, 232), shadow=True)
    img = card
    draw = ImageDraw.Draw(img)
    add_text(draw, (118, 268), "成品观感", FONT_H2, (18, 38, 58))
    bullets = [
        "像透明终端小窗，悬浮在桌面角落",
        "支持置顶、半透明、无边框",
        "主要交互还是输入命令或聊天",
        "可以放 ASCII 角色或小头像，但不像真正桌宠",
        "工程实现快，改造最省"
    ]
    y = 328
    for item in bullets:
        draw.ellipse((120, y + 9, 132, y + 21), fill=(66, 161, 255))
        add_text(draw, (148, y), item, FONT_BODY, (34, 55, 76))
        y += 58

    footer = "关键词：终端感 / 透明浮窗 / 开发者工具 / 实现成本低"
    add_text(draw, (88, 918), footer, FONT_SMALL, (210, 223, 238))

    out = OUT_DIR / "ghostty_pet_concept.png"
    img.save(out)
    return out


def draw_pet(draw, body_box, accent):
    x1, y1, x2, y2 = body_box
    draw.ellipse((x1 + 22, y2 - 26, x2 - 22, y2 + 18), fill=(18, 35, 56, 40))
    draw.rounded_rectangle((x1 + 38, y1 + 90, x2 - 38, y2 - 30), radius=70, fill=(248, 249, 246), outline=(210, 219, 226), width=3)
    draw.ellipse((x1 + 34, y1 + 8, x2 - 34, y1 + 164), fill=(250, 250, 248), outline=(210, 219, 226), width=3)
    draw.polygon([(x1 + 72, y1 + 54), (x1 + 110, y1 - 10), (x1 + 145, y1 + 60)], fill=(250, 250, 248), outline=(210, 219, 226))
    draw.polygon([(x2 - 72, y1 + 54), (x2 - 110, y1 - 10), (x2 - 145, y1 + 60)], fill=(250, 250, 248), outline=(210, 219, 226))
    draw.ellipse((x1 + 92, y1 + 74, x1 + 118, y1 + 104), fill=(42, 56, 70))
    draw.ellipse((x2 - 118, y1 + 74, x2 - 92, y1 + 104), fill=(42, 56, 70))
    draw.ellipse((x1 + 90, y1 + 104, x2 - 90, y1 + 132), fill=(255, 228, 226))
    draw.polygon([(x1 + 112, y1 + 120), ((x1 + x2) // 2, y1 + 142), (x2 - 112, y1 + 120)], fill=(239, 140, 120))
    draw.arc((x1 + 94, y1 + 120, x2 - 94, y1 + 170), 20, 160, fill=(78, 96, 116), width=4)
    draw.rounded_rectangle((x1 + 92, y1 + 190, x2 - 92, y1 + 234), radius=22, fill=accent)
    draw.rectangle((x1 + 126, y2 - 48, x1 + 162, y2 + 26), fill=(248, 249, 246), outline=(210, 219, 226))
    draw.rectangle((x2 - 162, y2 - 48, x2 - 126, y2 + 26), fill=(248, 249, 246), outline=(210, 219, 226))


def draw_pyside_mockup():
    img = draw_gradient((1600, 1000), (247, 229, 197), (232, 244, 236))
    draw = ImageDraw.Draw(img)

    draw.ellipse((1050, 80, 1520, 560), fill=(255, 196, 76, 86))
    draw.ellipse((40, 520, 540, 970), fill=(79, 173, 132, 70))
    draw.rounded_rectangle((0, 856, 1600, 1000), radius=0, fill=(234, 213, 184))
    for i in range(0, 1600, 90):
        draw.line((i, 862, i + 44, 1000), fill=(212, 188, 155), width=3)

    add_text(draw, (88, 72), "方案 B  ·  PySide6 真桌宠版", FONT_H1, (64, 48, 30))
    add_text(draw, (88, 132), "独立窗口壳 + 聊天气泡 + 宠物状态动画，更接近你说的电子宠物。", FONT_BODY, (98, 78, 56))

    bubble = speech_bubble(img, (880, 122, 1450, 310), (255, 255, 255, 244), outline=(226, 205, 178, 255))
    img = bubble
    draw = ImageDraw.Draw(img)
    add_text(draw, (918, 162), "主人，我已经把 CLI 结果整理好了。\n点我展开对话，右键可以切模式。", FONT_BODY, (66, 51, 34))

    panel = rounded_box(img, (930, 340, 1494, 892), 30, (255, 253, 249, 236), outline=(228, 210, 190, 255), width=2)
    img = panel
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((956, 368, 1468, 420), radius=18, fill=(244, 236, 224))
    add_text(draw, (980, 380), "Vox Pet", FONT_H2, (72, 57, 39))
    add_text(draw, (1290, 382), "team mode", FONT_SMALL, (133, 105, 78))

    msg1 = rounded_box(img, (968, 454, 1296, 540), 22, (241, 248, 255, 255), shadow=False)
    img = msg1
    msg2 = rounded_box(img, (1088, 564, 1460, 688), 22, (255, 242, 214, 255), shadow=False)
    img = msg2
    draw = ImageDraw.Draw(img)
    add_text(draw, (994, 478), "你：把这个 CLI 改成桌宠形态", FONT_BODY, (42, 58, 76))
    add_text(draw, (1116, 590), "Pet：建议拆成 Core / Event / UI 三层，\n这样既保留 CLI 内核，也能挂悬浮宠物。", FONT_BODY, (85, 62, 34))
    draw.rounded_rectangle((964, 804, 1458, 854), radius=18, fill=(250, 245, 238), outline=(225, 212, 193))
    add_text(draw, (988, 818), "给主人发消息...", FONT_SMALL, (164, 147, 128))
    draw.rounded_rectangle((1362, 806, 1452, 852), radius=16, fill=(98, 179, 132))
    add_text(draw, (1392, 818), "发送", FONT_SMALL, (255, 255, 255))

    pet_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pet_draw = ImageDraw.Draw(pet_overlay)
    draw_pet(pet_draw, (610, 498, 862, 858), (255, 208, 88))
    pet_shadow = pet_overlay.filter(ImageFilter.GaussianBlur(10))
    img = Image.alpha_composite(img, Image.new("RGBA", img.size, (0, 0, 0, 0)))
    img = Image.alpha_composite(img, pet_shadow)
    img = Image.alpha_composite(img, pet_overlay)
    draw = ImageDraw.Draw(img)

    info = rounded_box(img, (84, 230, 640, 690), 34, (255, 255, 255, 222), shadow=True)
    img = info
    draw = ImageDraw.Draw(img)
    add_text(draw, (118, 268), "成品观感", FONT_H2, (72, 57, 39))
    bullets = [
        "桌面上真的有一个角色形态的小宠物",
        "可点击、冒泡、切换表情和动作状态",
        "展开后是聊天面板，不是裸终端",
        "更适合非技术用户，也更有产品感",
        "实现复杂度更高，但体验明显更完整"
    ]
    y = 328
    for item in bullets:
        draw.ellipse((120, y + 9, 132, y + 21), fill=(110, 182, 128))
        add_text(draw, (148, y), item, FONT_BODY, (86, 66, 44))
        y += 58

    add_text(draw, (88, 918), "关键词：桌宠感 / 冒泡交互 / 独立面板 / 产品完成度高", FONT_SMALL, (112, 88, 63))

    out = OUT_DIR / "pyside6_pet_concept.png"
    img.save(out)
    return out


def main():
    outputs = [draw_ghostty_mockup(), draw_pyside_mockup()]
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
