from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    system = "/System/Library/Fonts/Supplemental"
    dejavu = "/usr/share/fonts/truetype/dejavu"
    candidates = [
        f"{system}/Arial Bold.ttf" if bold else f"{system}/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        f"{dejavu}/DejaVuSans-Bold.ttf" if bold else f"{dejavu}/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


COLORS = {
    "bg": "#f7f8fb",
    "ink": "#17202a",
    "muted": "#607080",
    "blue": "#1d64d8",
    "green": "#167a4a",
    "panel": "#ffffff",
    "line": "#d8e0e7",
    "dark": "#10233a",
}


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=2)


def label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int = 22,
    bold: bool = False,
    fill: str = COLORS["ink"],
) -> None:
    draw.text(xy, text, font=font(size, bold=bold), fill=fill)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str = COLORS["blue"],
) -> None:
    draw.line([start, end], fill=color, width=4)
    ex, ey = end
    sx, sy = start
    if ex >= sx:
        head = [(ex, ey), (ex - 12, ey - 8), (ex - 12, ey + 8)]
    else:
        head = [(ex, ey), (ex + 12, ey - 8), (ex + 12, ey + 8)]
    draw.polygon(head, fill=color)


def architecture() -> None:
    img = Image.new("RGB", (1400, 820), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    label(draw, (60, 42), "wabot-agent Architecture", 34, True)
    label(
        draw,
        (60, 88),
        "Model-driven planning, harness-owned execution, local wabot control.",
        20,
        False,
        COLORS["muted"],
    )

    boxes = {
        "ui": (70, 170, 350, 320),
        "api": (420, 170, 700, 320),
        "agent": (770, 170, 1070, 320),
        "openrouter": (1120, 170, 1330, 320),
        "memory": (420, 420, 700, 570),
        "wabot": (770, 420, 1070, 570),
        "whatsapp": (1120, 420, 1330, 570),
        "mcp": (70, 420, 350, 570),
    }
    for name, box in boxes.items():
        fill = COLORS["dark"] if name == "agent" else COLORS["panel"]
        outline = COLORS["dark"] if name == "agent" else COLORS["line"]
        rounded(draw, box, fill, outline)

    label(draw, (102, 205), "Operator Dashboard", 23, True)
    label(draw, (102, 245), "Chat console\nreadiness\nrun history", 19, False, COLORS["muted"])
    label(draw, (452, 205), "FastAPI Service", 23, True)
    label(draw, (452, 245), "/api/chat\n/whatsapp/inbound\n/ready", 19, False, COLORS["muted"])
    label(draw, (802, 205), "Agents SDK Core", 23, True, "#ffffff")
    label(draw, (802, 245), "instructions\ntools\nMCP servers", 19, False, "#cfe2ef")
    label(draw, (1152, 205), "OpenRouter", 23, True)
    label(draw, (1152, 245), "OpenAI-compatible\nchat completions", 19, False, COLORS["muted"])
    label(draw, (452, 455), "SQLite Memory", 23, True)
    label(draw, (452, 495), "contact facts\nagent notes\nidempotency", 19, False, COLORS["muted"])
    label(draw, (802, 455), "wabot Daemon", 23, True)
    label(draw, (802, 495), "GET /health\nPOST /send\nPOST /send-image", 19, False, COLORS["muted"])
    label(draw, (1152, 455), "WhatsApp", 23, True)
    label(draw, (1152, 495), "linked device\nmessages\nmedia", 19, False, COLORS["muted"])
    label(draw, (102, 455), "Skills + MCP", 23, True)
    label(
        draw,
        (102, 495),
        "local skills\noptional MCP\napproval-first",
        19,
        False,
        COLORS["muted"],
    )

    arrow(draw, (350, 245), (420, 245))
    arrow(draw, (700, 245), (770, 245))
    arrow(draw, (1070, 245), (1120, 245))
    arrow(draw, (770, 500), (700, 500))
    arrow(draw, (920, 320), (920, 420))
    arrow(draw, (1070, 500), (1120, 500))
    arrow(draw, (350, 500), (420, 500))

    label(
        draw,
        (60, 690),
        "Safety boundary: the model proposes; the Python harness enforces send policy,",
        20,
        False,
        COLORS["ink"],
    )
    label(
        draw,
        (60, 720),
        "redaction, memory rules, and wabot readiness.",
        20,
        False,
        COLORS["ink"],
    )
    img.save(DOCS / "agent-interactions.png")


def sequence() -> None:
    img = Image.new("RGB", (1400, 820), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    label(draw, (60, 42), "Inbound WhatsApp Processing Sequence", 34, True)
    label(
        draw,
        (60, 88),
        "Idempotent by message id, fail-closed by send policy.",
        20,
        False,
        COLORS["muted"],
    )

    lanes = [
        ("WhatsApp", 110),
        ("wabot", 330),
        ("FastAPI", 550),
        ("Agent", 770),
        ("Memory", 990),
        ("Policy", 1210),
    ]
    for name, x in lanes:
        label(draw, (x - 40, 150), name, 20, True)
        draw.line([(x, 190), (x, 720)], fill=COLORS["line"], width=3)

    steps = [
        (110, 330, 230, "message webhook"),
        (330, 550, 300, "POST /whatsapp/inbound"),
        (550, 990, 370, "dedupe + session memory"),
        (550, 770, 440, "run Agents SDK"),
        (770, 1210, 510, "send tool asks policy"),
        (1210, 330, 580, "allowed: local /send"),
        (330, 110, 650, "WhatsApp reply"),
    ]
    for start_x, end_x, y, text in steps:
        arrow(draw, (start_x, y), (end_x, y))
        label(draw, (min(start_x, end_x) + 18, y - 30), text, 17, False, COLORS["muted"])

    rounded(draw, (70, 720, 1330, 780), COLORS["panel"], COLORS["line"])
    label(
        draw,
        (100, 740),
        "If duplicate, unlinked, rate-limited, unauthorized, or not allowlisted:",
        20,
        True,
    )
    label(draw, (100, 765), "record the event and do not send.", 20, True)
    img.save(DOCS / "agent-sequence.png")


if __name__ == "__main__":
    architecture()
    sequence()
    print(f"Wrote {DOCS / 'agent-interactions.png'}")
    print(f"Wrote {DOCS / 'agent-sequence.png'}")
