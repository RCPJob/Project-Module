import clr
import System
from System.IO import File, Directory

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

clr.AddReference('RevitNodes')
import Revit
clr.ImportExtensions(Revit.Elements)   # UnwrapElement

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BuiltInParameter

doc = DocumentManager.Instance.CurrentDBDocument
view = doc.ActiveView  # used for bounding box context

# inputs
elements_in = IN[0]
path = IN[1]

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
    # Try bounding box in active view first, then model bbox
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
    # If no bbox, push it to the end
    return 1e18

def category_priority(cat):
    # Lower number = earlier within same Z band
    if cat == "Structural Foundations":
        return 0
    if cat == "Structural Columns":
        return 1
    if cat == "Structural Framing":
        return 2
    if cat == "Floors":
        return 3
    return 99

def safe_int(x):
    try:
        return int(x)
    except:
        return 0

# build sortable records
records = []

for e in elements:
    if e is None:
        continue

    # element id
    try:
        eid = e.Id.IntegerValue
    except:
        eid = ""

    # category
    try:
        cat = e.Category.Name if e.Category else ""
    except:
        cat = ""

    # level name (as before)
    level_name = param_str(e, BuiltInParameter.LEVEL_PARAM)
    if not level_name:
        level_name = param_str(e, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if not level_name:
        level_name = param_str(e, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)

    # your rule: foundations missing level -> "Foundation"
    if cat == "Structural Foundations" and not level_name:
        level_name = "Foundation"

    # phase created
    phase_created = param_str(e, BuiltInParameter.PHASE_CREATED)

    zmin = get_zmin(e)
    cprio = category_priority(cat)

    # store sort keys + output fields
    records.append([zmin, cprio, eid, cat, level_name, phase_created])

# sort bottom -> top
records.sort(key=lambda r: (r[0], r[1], safe_int(r[2])))

# output rows (NO z column)
rows = []
rows.append(["element_id", "category", "level_name", "phase_created"])

for r in records:
    zmin, cprio, eid, cat, level_name, phase_created = r
    rows.append([eid, cat, level_name, phase_created])

# write csv
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

OUT = "elements_in={}, rows_written={}, path={}".format(len(elements), len(rows), path)
