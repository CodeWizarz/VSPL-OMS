import math
import os
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1100
HEIGHT = 520
NUM_FRAMES = 24
FPS = 15

# Fonts
try:
    font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 20)
    font_sub = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 12)
    font_step = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 10)
    font_card_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 13)
    font_card_desc = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 11)
    font_badge = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 11)
    font_logo = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 16)
except Exception:
    font_title = font_sub = font_step = font_card_title = font_card_desc = font_badge = font_logo = ImageFont.load_default()

# Nodes definition
# Row 1 (y: 110 to 205): 4 cards
# Row 2 (y: 280 to 375): 4 cards + Vendor loop card
nodes = [
    {
        "id": "s0", "num": "STAGE 0", "title": "Sales Intake & OAR",
        "desc": "PO match & line allocation", "x": 45, "y": 105, "w": 185, "h": 92,
        "color": (56, 189, 248), "border": (30, 58, 138)
    },
    {
        "id": "s1", "num": "STAGE 1", "title": "Continuous Casting",
        "desc": "Alloy melt, spectro & Heat ledger", "x": 260, "y": 105, "w": 195, "h": 92,
        "color": (129, 140, 248), "border": (49, 46, 129)
    },
    {
        "id": "s2", "num": "STAGE 2", "title": "PPC Setup Planning",
        "desc": "Tooling, fixtures & WO release", "x": 485, "y": 105, "w": 195, "h": 92,
        "color": (168, 85, 247), "border": (88, 28, 135)
    },
    {
        "id": "s3", "num": "STAGE 3", "title": "Machining Centers",
        "desc": "F1 Turn, F2 CNC, F3 Finish, SP", "x": 710, "y": 105, "w": 200, "h": 92,
        "color": (6, 182, 212), "border": (21, 94, 117)
    },
    # Subcontractor Loop Card
    {
        "id": "s4", "num": "STAGE 4 (SCM)", "title": "Vendor Subcontracting",
        "desc": "Multi-gate DC send/receive", "x": 930, "y": 190, "w": 140, "h": 125,
        "color": (236, 72, 153), "border": (131, 24, 67)
    },
    # Row 2 (Right to Left flow)
    {
        "id": "s5", "num": "STAGE 5", "title": "Final Inspection & MRB",
        "desc": "CMM QA, scrap & rework hold", "x": 710, "y": 280, "w": 200, "h": 92,
        "color": (34, 197, 94), "border": (20, 83, 45)
    },
    {
        "id": "s6", "num": "STAGE 6", "title": "Packing Bay",
        "desc": "Serialized PKU codes & crating", "x": 485, "y": 280, "w": 195, "h": 92,
        "color": (16, 185, 129), "border": (6, 78, 59)
    },
    {
        "id": "s7", "num": "STAGE 7", "title": "BSR Bonded Storage",
        "desc": "PO-Committed + Buffer stock", "x": 260, "y": 280, "w": 195, "h": 92,
        "color": (20, 184, 166), "border": (19, 78, 74)
    },
    {
        "id": "s8", "num": "STAGE 8", "title": "Dispatch Bay",
        "desc": "Zero over-dispatch, Invoices & DC", "x": 45, "y": 280, "w": 185, "h": 92,
        "color": (14, 165, 233), "border": (12, 74, 110)
    },
]

# Pipeline paths for animated particle flow
# Each path is a list of points (x, y)
paths = [
    # S0 -> S1
    [(230, 151), (260, 151)],
    # S1 -> S2
    [(455, 151), (485, 151)],
    # S2 -> S3
    [(680, 151), (710, 151)],
    # S3 -> S4 (subcontract trip out)
    [(910, 140), (930, 210)],
    # S4 -> S3/S5 (subcontract inward)
    [(930, 290), (910, 315)],
    # S3 -> S5 direct drop
    [(810, 197), (810, 280)],
    # S5 -> S6
    [(710, 326), (680, 326)],
    # S6 -> S7
    [(485, 326), (455, 326)],
    # S7 -> S8
    [(260, 326), (230, 326)],
]

# Summary footer banner metrics
metrics = [
    ("Deterministic OMS Engine", "v3.3 Core Active", (56, 189, 248)),
    ("Conservation of Mass", "Mass Balanced", (168, 85, 247)),
    ("Subcontractor Tracking", "Zero Double-Counting", (236, 72, 153)),
    ("Unified BSR Custody", "17ms Query Speed", (16, 185, 129)),
    ("Dispatch Gatekeeper", "0% Over-Dispatch", (14, 165, 233)),
]

def draw_rounded_rect(draw, xy, r, fill, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)

frames = []

for frame_idx in range(NUM_FRAMES):
    # Base background
    img = Image.new("RGBA", (WIDTH, HEIGHT), (7, 11, 20, 255))
    draw = ImageDraw.Draw(img)

    # Subtle background grid dots
    for gx in range(40, WIDTH - 40, 35):
        for gy in range(40, HEIGHT - 40, 35):
            draw.point((gx, gy), fill=(25, 35, 55, 120))

    # Outer border with gradient-like neon edge
    draw_rounded_rect(draw, (3, 3, WIDTH - 4, HEIGHT - 4), r=16, fill=None, outline=(30, 41, 59, 200), width=1)
    draw_rounded_rect(draw, (5, 5, WIDTH - 6, HEIGHT - 6), r=14, fill=None, outline=(59, 130, 246, 60), width=1)

    # Top Header
    # Logo circle
    draw.ellipse([45, 30, 81, 66], fill=(37, 99, 235), outline=(96, 165, 250), width=2)
    draw.text((56, 36), "V", font=font_logo, fill=(255, 255, 255))

    draw.text((95, 32), "VSPL SMES • Real-Time Manufacturing Execution Pipeline", font=font_title, fill=(255, 255, 255))
    draw.text((95, 56), "Deterministic Shop Floor Movement, SCM Subcontracting Trips, Conservation of Mass & BSR Custody", font=font_sub, fill=(148, 163, 184))

    # Pulsing Live Badge top right
    pulse_alpha = int(128 + 127 * math.sin(2 * math.pi * frame_idx / NUM_FRAMES))
    pulse_radius = 5 + int(3 * math.sin(2 * math.pi * frame_idx / NUM_FRAMES))
    draw.rectangle([WIDTH - 180, 35, WIDTH - 45, 65], fill=(15, 23, 42), outline=(34, 197, 94, 160), width=1)
    draw.ellipse([WIDTH - 165 - pulse_radius, 50 - pulse_radius, WIDTH - 165 + pulse_radius, 50 + pulse_radius], fill=(34, 197, 94, pulse_alpha))
    draw.ellipse([WIDTH - 165 - 3, 50 - 3, WIDTH - 165 + 3, 50 + 3], fill=(34, 197, 94, 255))
    draw.text((WIDTH - 148, 43), "LIVE ENGINE", font=font_badge, fill=(52, 211, 153))

    # Draw static pipeline lines
    for p in paths:
        draw.line(p, fill=(40, 55, 80), width=4)

    # Draw animated particles moving along pipelines
    for p_idx, p in enumerate(paths):
        # Progress (0.0 to 1.0) with offset per path
        prog = ((frame_idx / NUM_FRAMES) + (p_idx * 0.15)) % 1.0
        x0, y0 = p[0]
        x1, y1 = p[-1]
        cx = int(x0 + (x1 - x0) * prog)
        cy = int(y0 + (y1 - y0) * prog)

        # Pulse color matches the stage
        pulse_col = (56, 189, 248) if p_idx < 3 else ((236, 72, 153) if p_idx < 5 else (16, 185, 129))
        # Outer glow
        draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(*pulse_col[:3], 90))
        # Bright core
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(255, 255, 255))

    # Draw Node Cards
    for node in nodes:
        x, y, w, h = node["x"], node["y"], node["w"], node["h"]
        col = node["color"]
        border_col = node["border"]

        # Card backdrop
        draw_rounded_rect(draw, (x, y, x + w, y + h), r=8, fill=(18, 26, 43, 245), outline=border_col, width=1)
        # Top color accent bar
        draw_rounded_rect(draw, (x + 1, y + 1, x + w - 1, y + 4), r=3, fill=col)

        # Step indicator
        draw.text((x + 10, y + 12), node["num"], font=font_step, fill=col)
        # Node Title
        draw.text((x + 10, y + 28), node["title"], font=font_card_title, fill=(248, 250, 252))
        # Node Description
        draw.text((x + 10, y + 50), node["desc"], font=font_card_desc, fill=(148, 163, 184))

        # Bottom status pill inside card
        draw_rounded_rect(draw, (x + 10, y + 70, x + w - 10, y + 84), r=4, fill=(10, 16, 28), outline=(30, 41, 59), width=1)
        # Small blinking dot inside card
        dot_on = (frame_idx + hash(node["id"])) % 6 < 3
        dot_col = col if dot_on else (60, 75, 100)
        draw.ellipse([x + 16, y + 75, x + 20, y + 79], fill=dot_col)
        draw.text((x + 25, y + 72), "ACTIVE GATE", font=font_step, fill=(100, 116, 139))

    # Footer Metric Bar
    draw_rounded_rect(draw, (45, 410, WIDTH - 45, 485), r=10, fill=(13, 20, 35), outline=(30, 45, 70), width=1)
    col_w = (WIDTH - 90) // len(metrics)
    for m_idx, (m_title, m_val, m_col) in enumerate(metrics):
        mx = 45 + m_idx * col_w
        draw.text((mx + 16, 425), m_title.upper(), font=font_step, fill=(100, 116, 139))
        draw.text((mx + 16, 445), m_val, font=font_card_title, fill=m_col)
        if m_idx < len(metrics) - 1:
            draw.line([(mx + col_w, 425), (mx + col_w, 470)], fill=(30, 45, 70), width=1)

    # Convert to RGB for GIF palette
    frames.append(img.convert("RGB"))

# Save as optimized animated GIF
output_path = os.path.abspath("docs/assets/workflow-animation.gif")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
frames[0].save(
    output_path,
    save_all=True,
    append_images=frames[1:],
    optimize=True,
    duration=int(1000 / FPS),
    loop=0
)

print(f"Successfully generated {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")
