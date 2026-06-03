import clr
import System
from System.IO import File, Directory

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

clr.AddReference('RevitNodes')
import Revit
clr.ImportExtensions(Revit.Elements)

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BuiltInParameter

doc = DocumentManager.Instance.CurrentDBDocument
view = doc.ActiveView

# inputs
elements_in = IN[0]
path = IN[1]
enable_validation = IN[2] if len(IN) > 2 else True

# unwrap
if isinstance(elements_in, list):
    elements = [UnwrapElement(x) for x in elements_in if x is not None]
else:
    elements = [UnwrapElement(elements_in)] if elements_in is not None else []

def param_str(e, bip):
    try:
        p = e.get_Parameter(bip)
        if not p:
            return ""
        s = p.AsValueString()
        if s:
            return s
        s = p.AsString()
        return s if s else ""
    except:
        return ""

def get_zmin(e):
    try:
        bb = e.get_BoundingBox(view)
        if bb and bb.Min:
            return float(bb.Min.Z)
    except:
        pass
    try:
        bb = e.get_BoundingBox(None)
        if bb and bb.Min:
            return float(bb.Min.Z)
    except:
        pass
    return 1e18

def get_family_and_type(e):
    """Extract family name and type name from element."""
    try:
        family_name = param_str(e, BuiltInParameter.ELEM_FAMILY_PARAM)
    except:
        family_name = ""
    
    try:
        type_name = param_str(e, BuiltInParameter.ELEM_TYPE_PARAM)
    except:
        type_name = ""
    
    return family_name.lower(), type_name.lower()

# NEW (Iteration 2): Effective category mapping
def get_effective_category(revit_category, family_name, type_name):
    """
    Map Revit category to effective sequencing category.
    
    Rules:
    - Structural Foundations → split into FOOTING or SLAB based on naming
    - Floors → SLAB
    - Structural Columns → COLUMN
    - Structural Framing → BEAM
    - Others → OTHER
    """
    
    if revit_category == "Structural Foundations":
        # Check family/type for footing patterns
        footing_patterns = ["footing", "pile", "pad", "pile cap", "strip"]
        slab_patterns = ["slab", "foundation slab", "transfer slab"]
        
        for pattern in footing_patterns:
            if pattern in family_name or pattern in type_name:
                return "FOOTING"
        
        for pattern in slab_patterns:
            if pattern in family_name or pattern in type_name:
                return "SLAB"
        
        # Default: if contains "slab" anywhere, treat as SLAB
        if "slab" in family_name or "slab" in type_name:
            return "SLAB"
        
        # Otherwise assume it's a footing
        return "FOOTING"
    
    elif revit_category == "Floors":
        return "SLAB"
    
    elif revit_category == "Structural Columns":
        return "COLUMN"
    
    elif revit_category == "Structural Framing":
        return "BEAM"
    
    else:
        return "OTHER"

def effective_priority(eff_cat):
    """Priority for effective categories. Lower = earlier."""
    priorities = {
        "FOOTING": 0,
        "COLUMN": 1,
        "BEAM": 2,
        "SLAB": 3,
        "OTHER": 99
    }
    return priorities.get(eff_cat, 99)

def safe_int(x):
    try:
        return int(x)
    except:
        return 0

# Build sortable records
records = []

for e in elements:
    if e is None:
        continue

    try:
        eid = e.Id.IntegerValue
    except:
        eid = ""

    try:
        revit_cat = e.Category.Name if e.Category else ""
    except:
        revit_cat = ""

    # Get family and type for effective category mapping
    family_name, type_name = get_family_and_type(e)
    
    # Compute effective category (NEW - Iteration 2)
    eff_cat = get_effective_category(revit_cat, family_name, type_name)

    # Level name
    level_name = param_str(e, BuiltInParameter.LEVEL_PARAM)
    if not level_name:
        level_name = param_str(e, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if not level_name:
        level_name = param_str(e, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)

    if revit_cat == "Structural Foundations" and not level_name:
        level_name = "Foundation"

    phase_created = param_str(e, BuiltInParameter.PHASE_CREATED)

    zmin = get_zmin(e)
    eff_priority = effective_priority(eff_cat)

    # Store: [sort_keys..., output_fields...]
    # sort_keys: (z_min, eff_priority, element_id)
    records.append({
        'zmin': zmin,
        'eff_priority': eff_priority,
        'eid': eid,
        'revit_cat': revit_cat,
        'eff_cat': eff_cat,
        'level_name': level_name,
        'phase_created': phase_created,
        'family_name': family_name,
        'type_name': type_name
    })

# Sort by (z_min, eff_priority, element_id)
records.sort(key=lambda r: (r['zmin'], r['eff_priority'], safe_int(r['eid'])))

# NEW (Iteration 2): Validate precedence rules
violations = []

if enable_validation:
    precedence_rules = [
        ("FOOTING", "COLUMN"),
        ("FOOTING", "BEAM"),
        ("FOOTING", "SLAB"),
        ("COLUMN", "BEAM"),
        ("COLUMN", "SLAB"),
        ("BEAM", "SLAB"),
    ]
    
    # Build a dict: eff_cat -> [indices in sorted order]
    cat_indices = {}
    for idx, r in enumerate(records):
        eff_cat = r['eff_cat']
        if eff_cat not in cat_indices:
            cat_indices[eff_cat] = []
        cat_indices[eff_cat].append(idx)
    
    # Check each rule
    for earlier_cat, later_cat in precedence_rules:
        if earlier_cat not in cat_indices or later_cat not in cat_indices:
            continue
        
        max_earlier_idx = max(cat_indices[earlier_cat])
        min_later_idx = min(cat_indices[later_cat])
        
        if max_earlier_idx > min_later_idx:
            # Violation: a later_cat element appears before an earlier_cat element
            violations.append({
                'rule': "{} before {}".format(earlier_cat, later_cat),
                'later_cat_idx': min_later_idx,
                'earlier_cat_idx': max_earlier_idx,
                'later_element': records[min_later_idx],
                'earlier_element': records[max_earlier_idx]
            })

# Output rows
rows = []
rows.append(["sequence_order", "element_id", "revit_category", "effective_category", 
             "level_name", "phase_created", "family_name", "type_name"])

for idx, r in enumerate(records):
    rows.append([
        idx + 1,  # sequence order (1-based)
        r['eid'],
        r['revit_cat'],
        r['eff_cat'],
        r['level_name'],
        r['phase_created'],
        r['family_name'],
        r['type_name']
    ])

# Write CSV
folder = System.IO.Path.GetDirectoryName(path)
if folder and not Directory.Exists(folder):
    Directory.CreateDirectory(folder)

def esc(v):
    if v is None:
        return ""
    s = str(v).replace('"', '""')
    if ("," in s) or ("\n" in s) or ("\r" in s):
        s = '"' + s + '"'
    return s

lines = []
for r in rows:
    lines.append(",".join([esc(x) for x in r]))

File.WriteAllLines(path, lines)

# Build output message
output_msg = "Iteration 2 - Effective Category Mapping\n"
output_msg += "Elements: {}\n".format(len(elements))
output_msg += "Rows written: {}\n".format(len(rows))
output_msg += "Path: {}\n".format(path)

if enable_validation:
    output_msg += "\nValidation: {} precedence rule(s) checked\n".format(len(violations))
    if violations:
        output_msg += "VIOLATIONS FOUND: {}\n".format(len(violations))
        for v in violations:
            output_msg += "  - {} (row {}: {} before row {}: {})\n".format(
                v['rule'],
                v['later_cat_idx'] + 2,  # +2 for 1-based + header
                v['later_element']['eid'],
                v['earlier_cat_idx'] + 2,
                v['earlier_element']['eid']
            )
    else:
        output_msg += "No precedence violations detected.\n"

OUT = output_msg
