---
name: analysis-ready-product-mapper
description: Maps science use cases to official NISAR analysis-ready products (L2/L3)
with confidence levels and handles uncertainty gracefully.
---

# Product Mapper Skill Instructions

## Purpose
This skill helps users determine which NISAR analysis-ready product is suited for
specific science use cases. It maps science use cases to official NISAR analysis-ready
products (L2 and L3) based on the current product documentation and capabilities.

## Workflow

1. **Receive Input**: A science use case description (e.g., "calculate snow depth",
   "ice velocity", "soil moisture")

2. **Lookup Process**:
   - Search `analysis-ready-product-rules.md` for a matching use case
   - If found, retrieve the recommended NISAR product(s)
   - If not found, flag as "unknown use case"

3. **Output**:
   - Recommended NISAR analysis-ready product(s)
   - Product type: L2 (Geocoded) or L3 (Geophysical)
   - Confidence level (HIGH/MEDIUM/LOW)
   - Reasoning/why this product works
   - Uncertainty flag if applicable

4. **Handle Uncertainty**:
   - For ambiguous cases, suggest multiple products
   - For missing use cases, recommend consulting NISAR documentation or domain expert
   - For complex parameters, explain what additional information is needed
