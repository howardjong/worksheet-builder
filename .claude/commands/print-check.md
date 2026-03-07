---
description: Validate a generated PDF for print readiness (dimensions, margins, fonts, DPI, accessibility)
argument-hint: "[path to PDF file]"
---

You are validating a generated worksheet PDF for print readiness.

Target PDF: $ARGUMENTS

Inspect the PDF using PyMuPDF (fitz) and check:

1. **Page dimensions:** letter size (8.5 x 11" = 612 x 792 points)
2. **Margins:** all content within 0.75" (54 point) margin-safe area
3. **Fonts:** all fonts embedded (no system font dependencies)
4. **Text rendering:** text is vector (searchable), not rasterized images of text
5. **Raster assets:** any embedded images are >= 300 DPI at their rendered size
6. **Color contrast:** text-to-background contrast meets WCAG AA (4.5:1 for normal text, 3:1 for large text)
7. **Font size:** meets grade-level minimum (K: 16pt, G1: 14pt, G2-3: 12pt)
8. **Visual collisions:** no overlapping text and image bounding boxes
9. **Page count:** reasonable for the adapted activity (not overflowing)

Run the checks by reading the PDF with PyMuPDF and produce:

```
## Print Quality Report: [filename]

### Status: [PASS / ISSUES FOUND]

| Check | Status | Measured | Required | Notes |
|-------|--------|----------|----------|-------|
| Page size | ... | 612x792pt | 612x792pt | ... |
| Margins | ... | ... | 54pt min | ... |
| Fonts embedded | ... | [count] | all | ... |
| Vector text | ... | ... | yes | ... |
| Raster DPI | ... | ... | >=300 | ... |
| Contrast | ... | ... | >=4.5:1 | ... |
| Font size | ... | ... | grade-dependent | ... |
| Collisions | ... | [count] | 0 | ... |
```

$ARGUMENTS
