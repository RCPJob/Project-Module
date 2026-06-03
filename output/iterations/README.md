# Structural Element Ordering Iterations

This directory contains CSV exports from Dynamo Python script analysis of structural elements in the Revit model.

## Files Overview

### Iteration_1.csv & Iteration_2.csv
**Basic structural element sorting**
- Columns: `element_id`, `category`, `level_name`, `phase_created`
- Sorted by Z-height (bottom to top) and category priority
- Category priority order:
  1. Structural Foundations
  2. Structural Columns
  3. Structural Framing
  4. Floors
- **Use case:** Simple construction sequencing by level and phase

### Iteration_3.csv
**Enhanced with spatial and staging data**
- Added columns: `zone_order`, `level_order`, `stage`, `zone`, `effective_category`, `zmin`
- Stage values encode: generic sequence number (e.g., `99900036020`)
- Z-coordinates (zmin) show actual element heights in feet
- Zones marked as "UNZONED"
- **Use case:** Better spatial organization with coordinate tracking

### Iteration_4.csv (Latest)
**Hierarchical staged ordering - RECOMMENDED**
- Stage column uses hierarchical encoding: `{zone_order}{level_order}{zmin_encoded}{element_id}`
  - Example: `1001009993602439356` = Zone(1) + Level(0) + Z-height-encoded + ElementID(439356)
- Zone unified to "ZONE_ALL" (single construction zone)
- All elements fully sortable and sequenceable
- **Use case:** Advanced construction phasing, BIM coordination, 4D scheduling

## Key Data Points

- **Total Elements:** 132
- **Foundation Level:** 40 elements (Footings + Columns)
- **Ground Floor (GF):** 22 elements
- **First Floor (FF):** 30 elements (Columns + Beams + Slab)
- **Second Floor (SF):** 30 elements (Columns + Beams + Slab)
- **Third Floor (TF):** 10 elements (Beams + Slab)

## Effective Categories

- **FOOTING:** Foundation footings
- **COLUMN:** Structural columns
- **BEAM:** Structural framing members
- **SLAB:** Floor slabs/floors

## Recommended Usage

1. **For construction sequencing:** Use Iteration_4.csv with the `stage` column for proper scheduling
2. **For zone-based coordination:** Expand `zone` column categories when adding multiple construction zones
3. **For clash detection:** Use `element_id` + `effective_category` + `level_name` for spatial queries
4. **For phasing:** Match elements by `phase_created` column from earlier iterations

## Notes

- Z-coordinates in Iteration_3 & 4 are in feet (Revit model units)
- Foundation level elements show negative Z values (below ground)
- Stage values are sortable as integers for proper sequencing
