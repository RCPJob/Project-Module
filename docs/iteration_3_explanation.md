# Iteration 3: Spatial Zoning (Work Packages by Grid/Area)

## Problem (from Iteration 1 & 2)

Iterations 1 and 2 produce a **global sequence**: all elements sorted by Z-coordinate and precedence rules, regardless of location in the building.

**Real construction doesn't work this way.** In practice:
- Crews work **zone-by-zone** (e.g., grid bay A-B / 1-2, then A-B / 2-3, etc.)
- They complete all structural work in one zone before moving to the next
- Mixing elements from different areas creates inefficiency (excessive crew movement, logistics overhead)

**Example of problem:**
```
Iteration 2 (global) sequence:
  1. Footing at (X:0-5m, Y:0-5m)
  2. Footing at (X:10-15m, Y:10-15m)  ← different area, inefficient!
  3. Column at (X:0-5m, Y:0-5m)
  4. Column at (X:10-15m, Y:10-15m)
  ... etc
```

**Iteration 3 (zoned) sequence:**
```
Zone A (X:0-5m, Y:0-5m):
  1. Footing in Zone A
  2. Column in Zone A
  3. Beam in Zone A
  4. Slab in Zone A

Zone B (X:5-10m, Y:0-5m):
  5. Footing in Zone B
  6. Column in Zone B
  7. Beam in Zone B
  8. Slab in Zone B
  ... and so on, zone-by-zone
```

This matches real project execution (work packages), improving validity for planning.

## Solution: Spatial Zoning via Grid/Bounding Boxes

### Approach 1: Grid-Based Zoning (Recommended for Orthogonal Buildings)

If the building has a regular grid (columns at regular intervals):
1. Extract grid lines from the model (Grids in Revit)
2. Use grid intersections to define zones (e.g., "Grid A-B / 1-2")
3. Assign each element to the zone(s) it overlaps
4. Sequence zone-by-zone, applying Iteration 2 rules within each zone

### Approach 2: Bounding Box Clustering (Generic)

For buildings without clear grids or custom zoning:
1. Divide the model's bounding box into a regular grid (e.g., 10m × 10m tiles)
2. Assign each element to the zone(s) its centroid or bounding box falls into
3. Apply grid-based sequencing

### Approach 3: User-Defined Zones (Most Flexible)

Let users specify zones manually (e.g., via CSV input or Revit Linked Models as zone markers).

---

## Implementation Strategy (Iteration 3)

We'll implement **Approach 2 (Bounding Box Clustering)** as a foundation. This is:
- ✅ Generic (works for any building shape)
- ✅ Parameterized (grid cell size is configurable)
- ✅ Extensible (can be enhanced to read Revit grids later)

### Algorithm

```
1. INPUT: elements + grid_cell_size (e.g., 10m)

2. COMPUTE global bounding box of all elements
   bbox_min = (min_x, min_y)
   bbox_max = (max_x, max_y)

3. DIVIDE into zones:
   zone_cols = ceil((max_x - min_x) / grid_cell_size)
   zone_rows = ceil((max_y - min_y) / grid_cell_size)
   
   For each cell (i, j):
     zone_bounds = {
       "min_x": min_x + i * grid_cell_size,
       "max_x": min_x + (i+1) * grid_cell_size,
       "min_y": min_y + j * grid_cell_size,
       "max_y": min_y + (j+1) * grid_cell_size,
       "label": f"Zone_{i}_{j}"
     }

4. ASSIGN each element to zone(s):
   For each element e:
     centroid = (centroid_x, centroid_y, centroid_z)
     zone_i = floor((centroid_x - min_x) / grid_cell_size)
     zone_j = floor((centroid_y - min_y) / grid_cell_size)
     element.zone = f"Zone_{zone_i}_{zone_j}"

5. SEQUENCE within each zone (Iteration 2 rules):
   For each zone (in order):
     elements_in_zone = [e for e in elements if e.zone == zone]
     sort elements_in_zone by (z_min, eff_priority, id)
     add to global sequence

6. OUTPUT: 
   - CSV with zone assignment
   - Zone-based sequence (sequential index resets by zone? or continuous?)
   - Zone summary report
```

### Key Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Grid cell size** | User input (default: 10m) | Parameterized for flexibility |
| **Zone assignment** | Centroid-based | Simple, deterministic |
| **Sequence numbering** | Continuous (global) | Easier to map back to elements |
| **Zone traversal order** | Left-to-right, bottom-to-top (i, j order) | Mimics typical site workflow |
| **Unassigned elements** | Optional handling (assign to nearest zone or "UNZONED") | Robustness |

---

## Code Changes (Iteration 2 → Iteration 3)

### New Input Parameter

```python
IN[3] = grid_cell_size  # default: 10 (meters)
```

### New Functions

| Function | Purpose |
|----------|---------|
| `get_element_centroid(e, view)` | Get XY centroid from bounding box |
| `compute_zone_grid(elements, grid_cell_size)` | Compute zone boundaries and assign elements |
| `assign_elements_to_zones(elements, zones)` | Map each element to zone(s) |
| `sequence_by_zones(records, grid_cell_size)` | Apply Iteration 2 sorting per zone |

### Output CSV Enhancements

**New columns:**
- `zone_id`: assigned zone (e.g., "Zone_0_1")
- `zone_label`: human-readable zone name (e.g., "Grid A-B / 1-2")  ← future
- `seq_in_zone`: sequence order within that zone (for debugging)

**Example:**
```csv
sequence_order,element_id,effective_category,zone_id,seq_in_zone,level_name,...
1,123,FOOTING,Zone_0_0,1,Foundation,...
2,456,COLUMN,Zone_0_0,2,Level 1,...
3,789,BEAM,Zone_0_0,3,Level 1,...
4,654,SLAB,Zone_0_0,4,Level 1,...
5,111,FOOTING,Zone_1_0,1,Foundation,...
6,222,COLUMN,Zone_1_0,2,Level 1,...
...
```

### Console Output Example

```
Iteration 3 - Spatial Zoning (Work Packages)
Elements: 42
Rows written: 43
Path: C:\output\sequence_iteration3.csv
Grid cell size: 10.0m

Zone Summary:
  Zone_0_0: 4 elements (1 FOOTING, 1 COLUMN, 1 BEAM, 1 SLAB)
  Zone_0_1: 5 elements (1 FOOTING, 2 COLUMNS, 1 BEAM, 1 SLAB)
  Zone_1_0: 6 elements (1 FOOTING, 1 COLUMN, 2 BEAMS, 2 SLABS)
  ... (total 7 zones)

Validation: 6 precedence rule(s) checked per zone
  Zone_0_0: No violations
  Zone_0_1: No violations
  Zone_1_0: No violations
  ... (all zones: PASS)
```

---

## How to Use in Dynamo

**Inputs:**

| Input | Type | Description |
|-------|------|-------------|
| `IN[0]` | Element(s) | Revit elements to sequence |
| `IN[1]` | String | CSV output file path |
| `IN[2]` | Boolean | Enable validation (default: True) |
| `IN[3]` | Float | Grid cell size in meters (default: 10.0) |

**Example:**
```
IN[0] → [Selected structural elements]
IN[1] → "C:\Project\sequence_iteration3.csv"
IN[2] → True
IN[3] → 10.0  (10m × 10m zones)
```

---

## Improvements Over Iteration 2

✅ **Work packages**: Output respects spatial logic (crews work zone-by-zone)  
✅ **Realistic sequencing**: Closer to how projects are actually built  
✅ **Traceability per zone**: CSV shows zone assignment and in-zone sequence  
✅ **Parameterized**: Grid size adjustable for different project scales  
✅ **Scalable**: Can handle multi-storey by combining with level filters

## Limitations

- **Centroid-based assignment**: Elements straddling zone boundaries assigned to one zone only (could be refined)
- **Fixed grid**: Regular grid may not match irregular building layouts
- **No temporal stagger**: Doesn't model crew size, activity duration, or dependencies between zones
- **No construction sequencing logic**: Doesn't know if zones must be built in sequence or can be parallel

## Next Steps (Iteration 4)

Add **dependency graph representation**:
- Model as directed acyclic graph (DAG)
- Nodes: (zone, category) pairs (e.g., "Zone_0_0 FOOTING" → action)
- Edges: precedence dependencies
- Output: GraphML or JSON for import into scheduling tools (MS Project, Primavera)

**Example (Iteration 4):**
```
Zone_0_0_FOOTING → Zone_0_0_COLUMN → Zone_0_0_BEAM → Zone_0_0_SLAB
                                                           ↓
                                         Zone_0_1_FOOTING (if zones sequential)
```

This generalizes beyond one storey and enables quantitative scheduling analysis (critical path, slack times, etc.).

---

## Files to Create

1. **`scripts/iteration_3_spatial_zoning.py`** — Full implementation
2. **`docs/iteration_3_explanation.md`** — This document (documentation)
