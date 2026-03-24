---
name: Print-Quality PDF Standards
description: This skill should be used when the user asks to "generate a PDF", "render a worksheet", "create print output", "set margins", "embed fonts", or when code in render/pdf.py is being created or modified. It enforces print-ready PDF specifications.
version: 1.0.0
---

# Print-Quality PDF Standards

All generated worksheets are print-first. The PDF must be physically printable at high quality.

## Hard Specifications
- **Page size:** Letter (8.5 x 11" = 612 x 792 points)
- **Margins:** 0.75" (54 points) safe area on all sides — no content outside this
- **Text rendering:** vector only (ReportLab text objects, NOT rasterized text images)
- **Fonts:** fully embedded with fallback stack (never rely on system fonts)
- **Raster assets:** minimum 300 DPI at rendered size
- **Color space:** RGB for screen preview, CMYK-safe colors for print
- **File format:** PDF 1.4+ with optional PDF/A archival variant

## ReportLab Implementation Notes
- Use `canvas.Canvas` or `platypus` for layout
- Use `pdfmetrics.registerFont()` + `TTFont` for font embedding
- Use `drawString()` / `Paragraph` for text (vector)
- Use `drawImage()` for raster illustrations — verify DPI: `image_px / rendered_inches >= 300`
- Set `pagesize=letter` from `reportlab.lib.pagesizes`
- Use `cm` or `inch` units from `reportlab.lib.units` for margin calculations

## Content Placement
- Instructions: top-left of content area
- Worked example: shaded box below instructions
- Activity items: main body, chunked with visual separators
- Progress indicator: bottom of content area
- Avatar companion: fixed position (e.g., bottom-right), same position every page
- Decorative elements: within defined decoration zones only, max 2 per page

## Validation Checks (validate/print_checks.py)
1. Page dimensions match letter size
2. All text objects within margin-safe area
3. All fonts are embedded (no Type 3 or system-only fonts)
4. Raster images meet 300 DPI threshold
5. No overlapping text and image bounding boxes
6. Contrast ratio meets WCAG AA (4.5:1 normal text, 3:1 large text)
7. Font sizes meet grade-level minimums
