"""Export dot lists to plotter-ready SVG files."""

import svgwrite


def export_svg(
    dots: list[tuple[float, float, float]],
    img_width_px: int,
    img_height_px: int,
    output_path: str,
    output_width_mm: float = 100.0,
    stroke_color: str = "black",
    fill: bool = True,
) -> None:
    """
    Write an SVG containing one <circle> per dot.

    Coordinates are scaled so the image maps to output_width_mm × computed_height_mm.
    Radii are scaled by the same factor.
    """
    scale = output_width_mm / img_width_px
    output_height_mm = img_height_px * scale

    dwg = svgwrite.Drawing(
        output_path,
        size=(f"{output_width_mm}mm", f"{output_height_mm}mm"),
        viewBox=f"0 0 {output_width_mm} {output_height_mm}",
    )

    fill_color = stroke_color if fill else "none"
    stroke_w = 0 if fill else max(0.05, scale * 0.5)

    for cx, cy, r in dots:
        dwg.add(
            dwg.circle(
                center=(round(cx * scale, 4), round(cy * scale, 4)),
                r=round(r * scale, 4),
                fill=fill_color,
                stroke=stroke_color if not fill else "none",
                stroke_width=stroke_w,
            )
        )

    dwg.save()
