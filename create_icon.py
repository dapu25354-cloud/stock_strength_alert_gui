from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "zhishen_alert.ico"
SIZE = 256


def font(size: int):
    candidates = [
        r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\NotoSansTC-Regular.otf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


image = Image.new("RGBA", (SIZE, SIZE), "#102a43")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((10, 10, 246, 246), radius=42, fill="#173f5f", outline="#7bdff2", width=5)
draw.line((38, 176, 79, 139, 114, 153, 159, 88, 215, 54), fill="#ffffff", width=12, joint="curve")
draw.polygon((204, 48, 221, 51, 216, 68), fill="#ffffff")
for center, color in (((57, 63), "#ffd166"), ((105, 63), "#70e000"), ((153, 63), "#3bf4a4")):
    draw.ellipse((center[0] - 15, center[1] - 15, center[0] + 15, center[1] + 15), fill=color, outline="#ffffff", width=3)
draw.rounded_rectangle((36, 194, 220, 224), radius=12, fill="#102a43")
draw.text((53, 198), "4551", font=font(22), fill="#ffffff")
image.save(OUTPUT, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
print(OUTPUT)
