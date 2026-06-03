# Iteration 2: Effective Category Mapping & Precedence Validation

## Problem (from Iteration 1)

The baseline Iteration 1 script used **Revit categories directly** for sequencing:
- `Structural Foundations` (priority 0)
- `Structural Columns` (priority 1)
- `Structural Framing` (priority 2)
- `Floors` (priority 3)

However, **`Structural Foundations` contains ambiguous elements**:
- **Footings** (substructure, must come first): pads, piles, pile caps, strip foundations
- **Foundation slabs** (horizontal elements at upper levels): slabs placed on top of columns/beams

When sorted by Z-min, an upper-level foundation slab naturally appeared after columns/beams. But under the rule "Structural Foundations come first," this was flagged as a violation—incorrectly.

## Solution: Effective Category Mapping

Instead of relying on Revit categories, **map each element to an effective sequencing category** based on family/type naming patterns.

### Mapping Rules

```
Revit Category: "Structural Foundations"
├─ If family/type contains ["footing", "pile", "pad", "pile cap", "strip"]
│  → Effective Category: FOOTING
│
└─ Else if family/type contains ["slab", "foundation slab", "transfer slab"]
   → Effective Category: SLAB

Revit Category: "Floors"
└─ → Effective Category: SLAB

Revit Category: "Structural Columns"
└─ → Effective Category: COLUMN

Revit Category: "Structural Framing"
└─ → Effective Category: BEAM

Others
└─ → Effective Category: OTHER
```

### Precedence Rules (Construction Logic)

```
FOOTING → COLUMN → BEAM → SLAB
```

This means:
1. All FOOTINGs must be placed before any COLUMNs
2. All COLUMNs must be placed before any BEAMs
3. All BEAMs must be placed before any SLABs (floors or foundation slabs)

## Key Changes from Iteration 1

### New Functions

| Function | Purpose |
|----------|---------|
| `get_family_and_type(e)` | Extract family and type names (lowercase) for pattern matching |
| `get_effective_category(...)` | Map Revit category → effective category using naming patterns |
| `effective_priority(eff_cat)` | Return priority value (FOOTING=0, COLUMN=1, BEAM=2, SLAB=3, OTHER=99) |

### Validation Logic (NEW)

```python
if enable_validation:
    # Define 6 precedence rules
    precedence_rules = [
        ("FOOTING", "COLUMN"),
        ("FOOTING", "BEAM"),
        ("FOOTING", "SLAB"),
        ("COLUMN", "BEAM"),
        ("COLUMN", "SLAB"),
        ("BEAM", "SLAB"),
    ]
    
    # For each rule, check if any violation exists
    # Violations: element of later_cat appears before element of earlier_cat
```

### Output CSV Changes

**New columns:**
- `sequence_order`: 1-based index in final sequence
- `effective_category`: mapped category (FOOTING/COLUMN/BEAM/SLAB/OTHER)
- `family_name`: element family name (used for disambiguation)
- `type_name`: element type name (used for disambiguation)

**Removed:**
- Z-min (internal sorting key, not exported)

**Structure:**
```csv
sequence_order,element_id,revit_category,effective_category,level_name,phase_created,family_name,type_name
1,123,Structural Foundations,FOOTING,Foundation,New Construction,Footing,Rectangular Pad
2,456,Structural Columns,COLUMN,Level 1,New Construction,Structural Column,W12x26
3,789,Structural Framing,BEAM,Level 1,New Construction,Structural Beam,W18x40
4,654,Floors,SLAB,Level 1,New Construction,Floor,Concrete Floor 200mm
```

### Console Output Example

```
Iteration 2 - Effective Category Mapping
Elements: 42
Rows written: 43
Path: C:\output\sequence.csv

Validation: 6 precedence rule(s) checked
VIOLATIONS FOUND: 2
  - FOOTING before COLUMN (row 15: 456 before row 8: 123)
  - BEAM before SLAB (row 22: 789 before row 12: 654)
```

## How to Use in Dynamo

**Inputs:**

| Input | Type | Description |
|-------|------|-------------|
| `IN[0]` | Element(s) | Revit elements to sequence |
| `IN[1]` | String | CSV output file path |
| `IN[2]` | Boolean | Enable validation (optional, default: True) |

**Example:**
```
IN[0] → [Selected structural elements from Revit model]
IN[1] → "C:\Project\sequence_iteration2.csv"
IN[2] → True (run validation)
```

## Improvements Over Iteration 1

✅ **False violations eliminated**: Upper-level foundation slabs no longer incorrectly flagged  
✅ **Intent-based classification**: Uses naming patterns, not just category  
✅ **Traceability**: Family/type names visible in CSV for debugging  
✅ **Formal rules**: Explicit precedence rules that can be documented and audited  
✅ **Extensible**: Naming patterns can be customized for project-specific families

## Limitations

- **Pattern-based matching**: Depends on consistent family naming conventions
- **No spatial awareness**: Still sorts globally (Z-min), not by zones
- **No temporal logic**: Doesn't model activity duration or crew workflow
- **No dependency feedback**: Rules are fixed; can't adapt to model changes

## Next Steps (Iteration 3)

Add **spatial zoning**: divide model into work packages (grid bays/areas) and sequence within each zone. This makes output closer to real site execution where crews work area-by-area.

**Example (Iteration 3):**
```
Zone A (columns 1-3):
  1. Footings in Zone A
  2. Columns in Zone A
  3. Beams in Zone A
  4. Slabs in Zone A

Zone B (columns 4-6):
  5. Footings in Zone B
  6. Columns in Zone B
  ... and so on
```
