from __future__ import annotations

from dataclasses import dataclass
from html import escape
import math
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent / "figures"

WIDTH = 1280
HEIGHT = 800
BG = "#F6F1E8"
INK = "#182026"
GRID = "#D6D1C7"
AXIS = "#7B7F82"
FALLBACK = "#0F4C5C"
INITIAL = "#C8553D"
CALIBRATED = "#3A7D44"
NEGATIVE = "#C8553D"
POSITIVE = "#3A7D44"
NEUTRAL = "#B8B3A7"


SCENARIOS = ["S1", "S2", "S3", "S4", "S5"]
SCENARIO_DESCRIPTIONS = {
    "S1": "Nominal",
    "S2": "Single vehicle",
    "S3": "Tight capacity",
    "S4": "Shorter workday",
    "S5": "No-drop",
}

BASELINE_MAKESPAN = [15778, 15778, 14268, 12178, 15778]
INITIAL_MAKESPAN = [25630, 25630, 20442, 22040, 25630]
CALIBRATED_MAKESPAN = [15694, 15694, 14221, 12094, 15694]

BASELINE_DISTANCE = [6936.10, 6936.10, 8362.79, 6936.10, 6936.10]
INITIAL_DISTANCE = [12545.34, 12545.34, 13902.68, 12545.34, 12545.34]
CALIBRATED_DISTANCE = [6936.10, 6936.10, 8362.79, 6936.10, 6936.10]

INITIAL_DELTA = [-62.44, -62.44, -43.27, -80.98, -62.44]
CALIBRATED_DELTA = [0.53, 0.53, 0.33, 0.69, 0.53]

SCREENING = [
    ("v20260216105011", -19.08, "Existing local artifact"),
    ("v20260216103502", -62.44, "Existing local artifact"),
    ("v20260315045420274714", -62.44, "Existing local artifact"),
    ("v20260315063816867841", -10.46, "Retrained candidate"),
    ("v20260315063819799285", 0.54, "Retrained candidate"),
    ("v20260315063820648976", -6.46, "Retrained candidate"),
    ("v20260315063821017757", 0.53, "Selected calibrated model"),
]


@dataclass
class PlotArea:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def fmt_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if value == int(value):
        return f"{int(value)}"
    return f"{value:.2f}"


def fmt_percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def svg_text(x: float, y: float, content: str, size: int = 20, weight: str = "400",
             fill: str = INK, anchor: str = "start", family: str = "Arial") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{escape(content)}</text>'
    )


def svg_rect(x: float, y: float, width: float, height: float, fill: str,
             rx: float = 0, stroke: str | None = None, stroke_width: float = 1) -> str:
    stroke_attr = ""
    if stroke:
        stroke_attr = f' stroke="{stroke}" stroke-width="{stroke_width}"'
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" '
        f'rx="{rx}" ry="{rx}"{stroke_attr} />'
    )


def svg_line(x1: float, y1: float, x2: float, y2: float, stroke: str = AXIS,
             stroke_width: float = 1, dash: str | None = None) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"{dash_attr} />'
    )


def svg_circle(cx: float, cy: float, r: float, fill: str) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" />'


def write_svg(path: Path, title: str, body: list[str]) -> None:
    content = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f"<title>{escape(title)}</title>",
        svg_rect(0, 0, WIDTH, HEIGHT, BG),
        *body,
        "</svg>",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def draw_header(title: str, subtitle: str) -> list[str]:
    return [
        svg_text(80, 70, title, size=34, weight="700", family="Georgia"),
        svg_text(80, 104, subtitle, size=18, fill="#41505A"),
        svg_line(80, 124, WIDTH - 80, 124, stroke="#BDB6A8", stroke_width=2),
    ]


def legend(items: list[tuple[str, str]], x: int, y: int, gap: int = 180) -> list[str]:
    elements: list[str] = []
    offset = 0
    for label, color in items:
        elements.append(svg_rect(x + offset, y - 12, 18, 18, color, rx=4))
        elements.append(svg_text(x + offset + 28, y + 2, label, size=16, fill="#33434D"))
        offset += gap
    return elements


def nice_step(max_value: float, tick_count: int = 5) -> float:
    rough = max_value / tick_count
    magnitude = 10 ** max(len(str(int(rough))) - 1, 0)
    return math.ceil(rough / magnitude) * magnitude


def grouped_bar_chart(
    title: str,
    subtitle: str,
    y_label: str,
    filename: str,
    series: list[tuple[str, str, list[float]]],
) -> None:
    plot = PlotArea(left=100, top=170, right=1180, bottom=640)
    max_value = max(max(values) for _, _, values in series)
    step = nice_step(max_value)
    y_max = step * 5

    body = draw_header(title, subtitle)
    body.extend(legend([(name, color) for name, color, _ in series], x=620, y=92, gap=170))

    for tick in range(6):
        value = tick * step
        y = plot.bottom - (value / y_max) * plot.height
        body.append(svg_line(plot.left, y, plot.right, y, stroke=GRID, stroke_width=1))
        body.append(svg_text(plot.left - 14, y + 6, fmt_number(value), size=15, anchor="end", fill="#54636C"))

    body.append(svg_line(plot.left, plot.top, plot.left, plot.bottom, stroke=AXIS, stroke_width=2))
    body.append(svg_line(plot.left, plot.bottom, plot.right, plot.bottom, stroke=AXIS, stroke_width=2))
    body.append(svg_text(42, 410, y_label, size=16, fill="#54636C"))

    group_width = plot.width / len(SCENARIOS)
    bar_width = group_width * 0.18
    offsets = [-bar_width * 1.3, 0, bar_width * 1.3]

    for index, scenario in enumerate(SCENARIOS):
        center_x = plot.left + group_width * index + group_width / 2
        body.append(svg_text(center_x, plot.bottom + 36, scenario, size=16, weight="700", anchor="middle"))
        body.append(svg_text(center_x, plot.bottom + 58, SCENARIO_DESCRIPTIONS[scenario], size=13, anchor="middle", fill="#54636C"))

        for (series_index, (_, color, values)) in enumerate(series):
            value = values[index]
            bar_height = (value / y_max) * plot.height
            x = center_x + offsets[series_index] - bar_width / 2
            y = plot.bottom - bar_height
            body.append(svg_rect(x, y, bar_width, bar_height, color, rx=6))
            body.append(svg_text(x + bar_width / 2, y - 10, fmt_number(value), size=13, anchor="middle", fill="#33434D"))

    write_svg(OUTPUT_DIR / filename, title, body)


def scenario_delta_chart() -> None:
    plot = PlotArea(left=110, top=170, right=1180, bottom=660)
    y_min = -90
    y_max = 10
    zero_y = plot.bottom - ((0 - y_min) / (y_max - y_min)) * plot.height

    body = draw_header(
        "Scenario-Level Change vs Fallback Baseline",
        "Positive values indicate improvement over fallback; negative values indicate worse planning performance.",
    )
    body.extend(legend([("Initial local ML", NEGATIVE), ("Calibrated ML", POSITIVE)], x=780, y=92, gap=170))

    for tick in range(y_min, y_max + 1, 10):
        y = plot.bottom - ((tick - y_min) / (y_max - y_min)) * plot.height
        body.append(svg_line(plot.left, y, plot.right, y, stroke=GRID, stroke_width=1))
        body.append(svg_text(plot.left - 14, y + 6, f"{tick}%", size=15, anchor="end", fill="#54636C"))

    body.append(svg_line(plot.left, plot.top, plot.left, plot.bottom, stroke=AXIS, stroke_width=2))
    body.append(svg_line(plot.left, zero_y, plot.right, zero_y, stroke=AXIS, stroke_width=2))
    body.append(svg_text(34, 410, "Makespan change (%)", size=16, fill="#54636C"))

    group_width = plot.width / len(SCENARIOS)
    bar_width = group_width * 0.22
    offsets = [-bar_width * 0.7, bar_width * 0.7]

    for index, scenario in enumerate(SCENARIOS):
        center_x = plot.left + group_width * index + group_width / 2
        body.append(svg_text(center_x, plot.bottom + 36, scenario, size=16, weight="700", anchor="middle"))
        body.append(svg_text(center_x, plot.bottom + 58, SCENARIO_DESCRIPTIONS[scenario], size=13, anchor="middle", fill="#54636C"))

        for delta, color, offset in (
            (INITIAL_DELTA[index], NEGATIVE, offsets[0]),
            (CALIBRATED_DELTA[index], POSITIVE, offsets[1]),
        ):
            y_value = plot.bottom - ((delta - y_min) / (y_max - y_min)) * plot.height
            x = center_x + offset - bar_width / 2
            rect_y = min(y_value, zero_y)
            rect_h = abs(zero_y - y_value)
            body.append(svg_rect(x, rect_y, bar_width, rect_h, color, rx=6))
            label_y = rect_y - 10 if delta >= 0 else rect_y + rect_h + 22
            body.append(svg_text(x + bar_width / 2, label_y, fmt_percent(delta), size=13, anchor="middle", fill="#33434D"))

    write_svg(OUTPUT_DIR / "figure_ch6_03_makespan_change_vs_fallback.svg", "Scenario-Level Change vs Fallback Baseline", body)


def screening_chart() -> None:
    plot = PlotArea(left=290, top=170, right=1170, bottom=700)
    x_min = -70
    x_max = 10

    body = draw_header(
        "Nominal-Scenario Model Screening",
        "Makespan change vs fallback baseline on Dataset 3. Positive values are better; negative values are worse.",
    )
    body.extend(
        legend(
            [
                ("Worse than fallback", NEGATIVE),
                ("Better than fallback", POSITIVE),
                ("Selected calibrated model", "#1F6E3E"),
            ],
            x=520,
            y=92,
            gap=190,
        )
    )

    for tick in range(x_min, x_max + 1, 10):
        x = plot.left + ((tick - x_min) / (x_max - x_min)) * plot.width
        body.append(svg_line(x, plot.top, x, plot.bottom, stroke=GRID, stroke_width=1))
        body.append(svg_text(x, plot.bottom + 34, f"{tick}%", size=15, anchor="middle", fill="#54636C"))

    zero_x = plot.left + ((0 - x_min) / (x_max - x_min)) * plot.width
    body.append(svg_line(zero_x, plot.top, zero_x, plot.bottom, stroke=AXIS, stroke_width=2))
    body.append(svg_text(730, 752, "Makespan change vs fallback baseline (%)", size=16, anchor="middle", fill="#54636C"))

    row_height = plot.height / len(SCREENING)
    bar_height = row_height * 0.56

    for index, (model, delta, family) in enumerate(SCREENING):
        y = plot.top + row_height * index + row_height / 2
        color = NEGATIVE if delta < 0 else POSITIVE
        if model == "v20260315063821017757":
            color = "#1F6E3E"

        body.append(svg_text(40, y - 6, model, size=16, weight="700"))
        body.append(svg_text(40, y + 18, family, size=13, fill="#54636C"))

        x_value = plot.left + ((delta - x_min) / (x_max - x_min)) * plot.width
        rect_x = min(zero_x, x_value)
        rect_w = abs(x_value - zero_x)
        body.append(svg_rect(rect_x, y - bar_height / 2, rect_w, bar_height, color, rx=8))
        anchor = "start" if delta >= 0 else "end"
        label_x = x_value + 12 if delta >= 0 else x_value - 12
        body.append(svg_text(label_x, y + 6, fmt_percent(delta), size=14, anchor=anchor, fill="#33434D"))

    write_svg(OUTPUT_DIR / "figure_ch6_04_nominal_model_screening.svg", "Nominal-Scenario Model Screening", body)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    grouped_bar_chart(
        title="Route Makespan by Scenario",
        subtitle="Dataset 3 local reruns comparing fallback baseline, initial local ML artifact, and calibrated local model.",
        y_label="Makespan (s)",
        filename="figure_ch6_01_makespan_by_scenario.svg",
        series=[
            ("Fallback baseline", FALLBACK, BASELINE_MAKESPAN),
            ("Initial local ML", INITIAL, INITIAL_MAKESPAN),
            ("Calibrated ML", CALIBRATED, CALIBRATED_MAKESPAN),
        ],
    )

    grouped_bar_chart(
        title="Route Distance by Scenario",
        subtitle="Total route distance stayed flat after calibration while the initial local ML artifact inflated the route plans.",
        y_label="Distance (m)",
        filename="figure_ch6_02_distance_by_scenario.svg",
        series=[
            ("Fallback baseline", FALLBACK, BASELINE_DISTANCE),
            ("Initial local ML", INITIAL, INITIAL_DISTANCE),
            ("Calibrated ML", CALIBRATED, CALIBRATED_DISTANCE),
        ],
    )

    scenario_delta_chart()
    screening_chart()


if __name__ == "__main__":
    main()
