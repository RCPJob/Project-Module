# -*- coding: utf-8 -*-
"""
Iteration 4: Reusable Sequencing Exporter (Production-Ready)
=============================================================

Dynamo Python (IronPython2) - Reusable sequencing exporter

PROBLEM SOLVED:
  Iteration 3 required Scope Boxes to be present for zoning. Real projects may not always
  have Scope Boxes defined, or they may be optional/incomplete. This iteration adds a 
  FALLBACK mode: if no Scope Boxes are found, all elements go into "ZONE_ALL" with 
  zone_order=1, and the export still works.
  
  This makes the script production-ready and reusable across projects with varying setups.

WHAT IT DOES:
  1) Extracts all elements from input
  2) Attempts to find Scope Boxes (with optional name filter)
  3) If Scope Boxes found: zones = scope boxes (as in Iteration 3)
     If NO Scope Boxes: zones = single "ZONE_ALL" (fallback mode)
  4) Assigns Level Order by element's Level parameter and Revit elevation
  5) Computes Stage (composite sort key): ZoneOrder * LevelOrder * (CategoryPriority + Z + ElementId)
  6) WRITES instance parameters: Zone, ZoneOrder, LevelOrder, Stage (if they exist)
  7) Exports CSV sorted by Stage (zone-first, then level, then category/Z within zone+level)

KEY IMPROVEMENTS OVER ITERATION 3:
  - Graceful fallback to "ZONE_ALL" if no Scope Boxes exist
  - Script is reusable on projects with or without Scope Boxes defined
  - Consistent output format regardless of zoning mode
  - Cleaner error handling and fallback logic

INPUT:
  IN[0] = elements (list)
          Recommended: Structural Foundations, Structural Columns, Structural Framing, Floors
  IN[1] = csv_output_path (string)
          e.g. "C:\\Temp\\sequence.csv"
  IN[2] = zone_filter (string or null, optional)
          If provided: only Scope Boxes whose names contain this string are used
          If blank/None: ALL Scope Boxes are considered
          Example: zone_filter="ZONE" to only use boxes named "ZONE_A", "ZONE_B", etc.

OUTPUT:
  CSV columns:
    zone_order, level_order, stage, level_name, zone, element_id, category, effective_category, zmin
  
  CSV sorted by:
    zone_order asc -> level_order asc -> stage asc -> element_id asc
  
  Instance parameters written to elements (if they exist as Project Parameters, Instance):
    - Zone (Text): name of Scope Box, or "ZONE_ALL" (fallback), "UNZONED", or "MULTI_ZONE"
    - ZoneOrder (Integer): sequence order of zone
    - LevelOrder (Integer): sequence order of level (by elevation)
    - Stage (Integer): composite sort key
  
  Diagnostic output:
    - Zoning mode: FALLBACK_ZONE_ALL or SCOPEBOX
    - Element count, Scope Box count
    - Parameter write counts
    - UNZONED / MULTI_ZONE counts
    - CSV path

ZONING MODES:
  1. SCOPEBOX (if Scope Boxes found):
     - Zones determined by which Scope Box(es) contain element XY center
     - Zone order: numeric (if all boxes have numbers in name) or left-to-right by X center
     - Unboxed elements: UNZONED (zone_order=999)
     - Multi-zone elements: MULTI_ZONE (zone_order=999)
  
  2. FALLBACK_ZONE_ALL (if NO Scope Boxes found or after filtering):
     - All elements in single zone "ZONE_ALL" with zone_order=1
     - No UNZONED or MULTI_ZONE entries (cleaner output for simple projects)
     - Simplifies scheduling for single-zone or single-building projects

EFFECTIVE CATEGORY MAPPING (unchanged from Iteration 3):
  - Floors => SLAB
  - Structural Columns => COLUMN
  - Structural Framing => BEAM
  - Structural Foundations:
    * Is class Floor => SLAB (Foundation Slab/Mat detected by API type)
    * Contains keyword "slab"/"mat"/"raft" => SLAB
    * Contains footing synonym (whole-word phrase) => FOOTING
    * Is FamilyInstance (default) => FOOTING
    * Else => UNKNOWN_FOUNDATION
  - Other => OTHER

STAGE CALCULATION (deterministic, ensures reproducibility):
  stage = zorder * 10^18 + lorder * 10^15 + (cat_priority * 10^12 + zrank * 10^6 + eid)
  
  This ensures:
  1. Zone is primary sort key (highest magnitude)
  2. Level is secondary sort key
  3. Category priority is tertiary (within zone+level)
  4. Z-min (zrank) is quaternary (within category+level+zone)
  5. Element ID is final tie-breaker

LEVEL ORDER:
  - Computed from Revit Level elevations (sorted low to high)
  - Elements without level parameter get LevelOrder=0 (treated as foundation level)
  - Ensures consistent vertical ordering regardless of level names or project setup

REUSABILITY:
  - Works on projects with Scope Boxes (multi-zone construction)
  - Works on projects without Scope Boxes (single-zone or simple projects)
  - Works with or without Project Parameters defined (gracefully skips if not present)
  - Minimal project-specific dependencies (only uses standard Revit categories/parameters)
  - Can be used as-is or adapted for custom zoning logic
"""

import clr
import System
from System.IO import File, Directory
import re

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Level, Floor, FamilyInstance
)

doc = DocumentManager.Instance.CurrentDBDocument
view = doc.ActiveView

# -------------------------
# Inputs
# -------------------------
elements_in = IN[0]
csv_path = IN[1]

zone_filter = None
try:
    zone_filter = IN[2]
except:
    zone_filter = None

if zone_filter is not None:
    zone_filter = str(zone_filter).strip()
    if zone_filter == "":
        zone_filter = None

# -------------------------
# Helpers
# -------------------------
def esc(v):
    """Escape CSV values"""
    if v is None:
        return ""
    s = str(v).replace('"', '""')
    if ("," in s) or ("\n" in s) or ("\r" in s):
        s = '"' + s + '"'
    return s

def safe_int(x, default=0):
    """Safe integer conversion"""
    try:
        return int(x)
    except:
        return default

def get_bounding_box_any(e):
    """Get element bounding box (prefer model bbox for stability, fallback to view)"""
    # Model bbox first (stable, not view-dependent)
    try:
        bb = e.get_BoundingBox(None)
        if bb and bb.Min and bb.Max:
            return bb
    except:
        pass
    # View bbox fallback
    try:
        bb = e.get_BoundingBox(view)
        if bb and bb.Min and bb.Max:
            return bb
    except:
        pass
    return None

def get_zmin(e):
    """Get minimum Z coordinate of element"""
    bb = get_bounding_box_any(e)
    if not bb:
        return 1e18
    try:
        return float(bb.Min.Z)
    except:
        return 1e18

def bbox_center_xy(bb):
    """Compute XY center of bounding box"""
    return (bb.Min.X + bb.Max.X) * 0.5, (bb.Min.Y + bb.Max.Y) * 0.5

def xy_inside_bbox(x, y, bb):
    """Check if XY point is inside bounding box"""
    return (x >= bb.Min.X and x <= bb.Max.X and y >= bb.Min.Y and y <= bb.Max.Y)

def param_str(e, bip):
    """Extract parameter value as string"""
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

def get_level_name(e):
    """Extract level name with multiple fallbacks"""
    # Try common level parameters across categories
    name = param_str(e, BuiltInParameter.LEVEL_PARAM)
    if not name:
        name = param_str(e, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if not name:
        name = param_str(e, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
    if not name:
        name = param_str(e, BuiltInParameter.SCHEDULE_LEVEL_PARAM)
    return name

def try_get_level_id(e):
    """Try to extract Level ElementId from element parameters"""
    for bip in [
        BuiltInParameter.LEVEL_PARAM,
        BuiltInParameter.FAMILY_LEVEL_PARAM,
        BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
        BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
        BuiltInParameter.SCHEDULE_LEVEL_PARAM
    ]:
        try:
            p = e.get_Parameter(bip)
            # StorageType is enum; ToString is OK in IronPython
            if p and p.StorageType.ToString() == "ElementId":
                lid = p.AsElementId()
                if lid and lid.IntegerValue != -1:
                    return lid
        except:
            pass
    return None

def get_type_and_family_names(e):
    """Extract type and family names from element"""
    type_name = ""
    family_name = ""
    try:
        sym = getattr(e, "Symbol", None)
        if sym:
            try:
                type_name = sym.Name or ""
            except:
                pass
            try:
                family_name = sym.FamilyName or ""
            except:
                pass
    except:
        pass
    if not type_name:
        try:
            type_name = param_str(e, BuiltInParameter.SYMBOL_NAME_PARAM)
        except:
            pass
    return type_name, family_name

def tokenize_words(s):
    """Lowercase and split into alphanumeric chunks"""
    return re.findall(r"[a-z0-9]+", (s or "").lower())

def has_phrase(words, phrase_words):
    """Check if phrase_words appears as consecutive sequence in words"""
    L = len(phrase_words)
    for i in range(0, len(words) - L + 1):
        if words[i:i+L] == phrase_words:
            return True
    return False

# Footing synonyms for keyword matching
FOOTING_PHRASES = [
    ["footing"], ["pad"], ["pile"], ["pile", "cap"], ["pilecap"],
    ["strip"], ["combined"], ["isolated"], ["pier"], ["pedestal"], ["plinth"]
]

def effective_category(cat, type_name, family_name, element):
    """
    Map Revit category to construction category.
    Returns: FOOTING, COLUMN, BEAM, SLAB, UNKNOWN_FOUNDATION, OTHER
    """
    # Floors are always slabs
    if cat == "Floors":
        return "SLAB"
    if cat == "Structural Columns":
        return "COLUMN"
    if cat == "Structural Framing":
        return "BEAM"

    if cat == "Structural Foundations":
        # Foundation slabs/mats often come through API as Floor type
        try:
            if isinstance(element, Floor):
                return "SLAB"
        except:
            pass

        # Keyword-based detection
        blob = ((type_name or "") + " " + (family_name or "")).lower()
        if ("slab" in blob) or ("mat" in blob) or ("raft" in blob):
            return "SLAB"

        # Footing phrase matching
        words = tokenize_words(blob)
        for phr in FOOTING_PHRASES:
            if has_phrase(words, phr):
                return "FOOTING"

        # Default for family instance foundations is FOOTING
        try:
            if isinstance(element, FamilyInstance):
                return "FOOTING"
        except:
            pass

        return "UNKNOWN_FOUNDATION"

    return "OTHER"

def cat_priority(eff_cat):
    """
    Priority within zone+level: lower number = earlier in sequence
    """
    # Lower is earlier
    if eff_cat == "FOOTING":
        return 10
    if eff_cat == "COLUMN":
        return 20
    if eff_cat == "BEAM":
        return 30
    if eff_cat == "SLAB":
        return 40
    return 90

def set_param(e, pname, value):
    """Write instance parameter value (if parameter exists and is writable)"""
    p = e.LookupParameter(pname)
    if not p or p.IsReadOnly:
        return False
    try:
        if isinstance(value, int):
            p.Set(int(value))
        else:
            p.Set(str(value))
        return True
    except:
        return False

# -------------------------
# Unwrap inputs
# -------------------------
try:
    # UnwrapElement is available in Dynamo Python environment
    UnwrapElement
except:
    pass

if isinstance(elements_in, list):
    elems = [UnwrapElement(x) for x in elements_in if x is not None]
else:
    elems = [UnwrapElement(elements_in)] if elements_in is not None else []

# -------------------------
# Levels -> LevelOrder (by elevation)
# -------------------------
levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
levels_sorted = sorted(levels, key=lambda L: L.Elevation)
levelId_to_order = {}
for i, L in enumerate(levels_sorted):
    levelId_to_order[L.Id.IntegerValue] = i

def compute_level_order(e, cat_name):
    """Assign level order (based on element's level parameter and elevation)"""
    lid = try_get_level_id(e)
    if lid is None:
        # If missing level, keep at bottom by default
        return 0
    return levelId_to_order.get(lid.IntegerValue, 0)

# -------------------------
# Scope Boxes -> Zones (optional, with fallback)
# -------------------------
scopeboxes = []
try:
    sbs = (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
           .WhereElementIsNotElementType())
    for sb in sbs:
        try:
            nm = sb.Name
        except:
            nm = ""

        # Optional name filter
        if zone_filter and (zone_filter not in nm):
            continue

        bb = get_bounding_box_any(sb)
        if not bb:
            continue
        scopeboxes.append((nm, sb, bb))
except:
    pass

# FALLBACK MODE: if no scope boxes found, use single "ZONE_ALL" zone
NO_SCOPEBOX_MODE = (len(scopeboxes) == 0)

def zone_hits_for_element(e):
    """Find which Scope Boxes contain element (by XY center)"""
    bb = get_bounding_box_any(e)
    if not bb:
        return []
    x, y = bbox_center_xy(bb)
    hits = []
    for nm, sb, sbbb in scopeboxes:
        try:
            if xy_inside_bbox(x, y, sbbb):
                hits.append(nm)
        except:
            pass
    return hits

def parse_zone_number(name):
    """Extract first integer from zone name (e.g. "ZONE_1" -> 1)"""
    m = re.search(r"(\d+)", name or "")
    if not m:
        return None
    return safe_int(m.group(1), None)

# ZoneOrder map for scope boxes
if NO_SCOPEBOX_MODE:
    # Fallback: single zone with order 1
    scopebox_name_to_order = {"ZONE_ALL": 1}
else:
    scopebox_name_to_order = {}
    # If all scope boxes have a number in their name, use it; else left-to-right by X center
    nums = []
    all_have_numbers = True
    for nm, sb, bb in scopeboxes:
        n = parse_zone_number(nm)
        if n is None:
            all_have_numbers = False
            break
        nums.append((nm, n))

    if all_have_numbers:
        # Use numeric ordering from names
        for nm, n in nums:
            scopebox_name_to_order[nm] = int(n)
    else:
        # Fallback: left-to-right by X center
        def sb_center_x(t):
            bb = t[2]
            return (bb.Min.X + bb.Max.X) * 0.5
        sbs_lr = sorted(scopeboxes, key=sb_center_x)
        for i, t in enumerate(sbs_lr):
            scopebox_name_to_order[t[0]] = i + 1

# -------------------------
# Build records + write parameters
# -------------------------
records = []
unboxed = 0
multi = 0
w_zone = w_zoneorder = w_levelorder = w_stage = 0

TransactionManager.Instance.EnsureInTransaction(doc)

for e in elems:
    if not e:
        continue

    try:
        eid = e.Id.IntegerValue
    except:
        eid = 0

    try:
        cat = e.Category.Name if e.Category else ""
    except:
        cat = ""

    lvl_name = get_level_name(e)
    if cat == "Structural Foundations" and not lvl_name:
        lvl_name = "Foundation"

    # Zone assignment (with fallback)
    if NO_SCOPEBOX_MODE:
        # Fallback mode: all elements in ZONE_ALL
        zone = "ZONE_ALL"
        zorder = 1
    else:
        # Scopebox mode: check which zone(s) contain element
        hits = zone_hits_for_element(e)
        if len(hits) == 1:
            zone = hits[0]
        elif len(hits) == 0:
            zone = "UNZONED"
            unboxed += 1
        else:
            zone = "MULTI_ZONE"
            multi += 1
        zorder = scopebox_name_to_order.get(zone, 999)

    # Level order
    lorder = compute_level_order(e, cat)

    # Effective category + zmin
    type_name, fam_name = get_type_and_family_names(e)
    eff = effective_category(cat, type_name, fam_name, e)
    zmin = get_zmin(e)

    # Deterministic within-group key: category priority -> zmin -> element id
    try:
        zrank = int(round(zmin * 1000.0))
    except:
        zrank = 0

    within = cat_priority(eff) * 10**12 + (zrank + 10**9) * 10**6 + eid

    # Stage: composite sort key ensuring zone-first, then level, then within
    stage = int(zorder) * 10**18 + int(lorder) * 10**15 + int(within)

    # Write instance parameters if they exist in project
    if set_param(e, "Zone", zone):
        w_zone += 1
    if set_param(e, "ZoneOrder", int(zorder)):
        w_zoneorder += 1
    if set_param(e, "LevelOrder", int(lorder)):
        w_levelorder += 1
    if set_param(e, "Stage", int(stage)):
        w_stage += 1

    records.append((zorder, lorder, stage, lvl_name, zone, eid, cat, eff, zmin))

TransactionManager.Instance.TransactionTaskDone()

# -------------------------
# Sort + Export
# -------------------------
records_sorted = sorted(records, key=lambda r: (r[0], r[1], r[2], r[5]))

folder = System.IO.Path.GetDirectoryName(csv_path)
if folder and not Directory.Exists(folder):
    Directory.CreateDirectory(folder)

header = ["zone_order", "level_order", "stage", "level_name", "zone", "element_id", "category", "effective_category", "zmin"]
lines = [",".join(header)]
for r in records_sorted:
    lines.append(",".join([esc(x) for x in r]))

File.WriteAllLines(csv_path, lines)

sb_names = [t[0] for t in scopeboxes]
OUT = "\n".join([
    "RUN COMPLETE (Reusable sequencing exporter).",
    "Zoning mode: {}".format("FALLBACK_ZONE_ALL" if NO_SCOPEBOX_MODE else "SCOPEBOX"),
    "Elements processed: {}".format(len(elems)),
    "ScopeBoxes considered: {}{}".format(
        len(scopeboxes),
        (" (filter='{}')".format(zone_filter) if zone_filter else " (ALL scope boxes)")
    ),
    "ScopeBox names: {}".format(", ".join(sb_names) if sb_names else "NONE"),
    "Writes: Zone={}, ZoneOrder={}, LevelOrder={}, Stage={}".format(w_zone, w_zoneorder, w_levelorder, w_stage),
    "UNZONED: {}".format(unboxed),
    "MULTI_ZONE: {}".format(multi),
    "CSV path: {}".format(csv_path),
    "CSV sort: ZoneOrder asc -> LevelOrder asc -> Stage asc"
])
