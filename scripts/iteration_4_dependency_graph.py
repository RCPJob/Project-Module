import clr
import System
from System.IO import File, Directory
import math
import json

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
grid_cell_size = IN[3] if len(IN) > 3 else 10.0
graph_format = IN[4] if len(IN) > 4 else "json"  # NEW: "json" or "graphml"

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

def get_element_centroid(e, view):
    try:
        bb = e.get_BoundingBox(view)
        if bb and bb.Min and bb.Max:
            cx = (float(bb.Min.X) + float(bb.Max.X)) / 2.0
            cy = (float(bb.Min.Y) + float(bb.Max.Y)) / 2.0
            return (cx, cy)
    except:
        pass
    try:
        bb = e.get_BoundingBox(None)
        if bb and bb.Min and bb.Max:
            cx = (float(bb.Min.X) + float(bb.Max.X)) / 2.0
            cy = (float(bb.Min.Y) + float(bb.Max.Y)) / 2.0
            return (cx, cy)
    except:
        pass
    return (0.0, 0.0)

def get_family_and_type(e):
    try:
        family_name = param_str(e, BuiltInParameter.ELEM_FAMILY_PARAM)
    except:
        family_name = ""
    
    try:
        type_name = param_str(e, BuiltInParameter.ELEM_TYPE_PARAM)
    except:
        type_name = ""
    
    return family_name.lower(), type_name.lower()

def get_effective_category(revit_category, family_name, type_name):
    if revit_category == "Structural Foundations":
        footing_patterns = ["footing", "pile", "pad", "pile cap", "strip"]
        slab_patterns = ["slab", "foundation slab", "transfer slab"]
        
        for pattern in footing_patterns:
            if pattern in family_name or pattern in type_name:
                return "FOOTING"
        
        for pattern in slab_patterns:
            if pattern in family_name or pattern in type_name:
                return "SLAB"
        
        if "slab" in family_name or "slab" in type_name:
            return "SLAB"
        
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

def safe_float(x):
    try:
        return float(x)
    except:
        return 0.0

def compute_zone_grid_and_assign(elements, grid_cell_size):
    if not elements:
        return {}, {}, {}
    
    min_x, max_x = 1e18, -1e18
    min_y, max_y = 1e18, -1e18
    
    element_centroids = {}
    for e in elements:
        try:
            eid = e.Id.IntegerValue
        except:
            eid = ""
        
        cx, cy = get_element_centroid(e, view)
        element_centroids[eid] = (cx, cy)
        
        min_x = min(min_x, cx)
        max_x = max(max_x, cx)
        min_y = min(min_y, cy)
        max_y = max(max_y, cy)
    
    if min_x >= max_x or min_y >= max_y:
        return {}, element_centroids, {}
    
    gcs = safe_float(grid_cell_size)
    if gcs <= 0:
        gcs = 10.0
    
    zone_cols = int(math.ceil((max_x - min_x) / gcs)) + 1
    zone_rows = int(math.ceil((max_y - min_y) / gcs)) + 1
    
    zone_bounds = {}
    for i in range(zone_cols):
        for j in range(zone_rows):
            zone_id = "Zone_{}_{}".format(i, j)
            zone_bounds[zone_id] = {
                "min_x": min_x + i * gcs,
                "max_x": min_x + (i + 1) * gcs,
                "min_y": min_y + j * gcs,
                "max_y": min_y + (j + 1) * gcs,
                "i": i,
                "j": j
            }
    
    element_zone_map = {}
    zone_stats = {}
    
    for e in elements:
        try:
            eid = e.Id.IntegerValue
        except:
            eid = ""
        
        cx, cy = element_centroids.get(eid, (0.0, 0.0))
        
        zone_i = int(math.floor((cx - min_x) / gcs))
        zone_j = int(math.floor((cy - min_y) / gcs))
        
        zone_i = max(0, min(zone_i, zone_cols - 1))
        zone_j = max(0, min(zone_j, zone_rows - 1))
        
        zone_id = "Zone_{}_{}".format(zone_i, zone_j)
        element_zone_map[eid] = zone_id
        
        if zone_id not in zone_stats:
            zone_stats[zone_id] = {"count": 0, "categories": {}}
        zone_stats[zone_id]["count"] += 1
    
    return zone_bounds, element_zone_map, zone_stats

# Build records
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

    family_name, type_name = get_family_and_type(e)
    eff_cat = get_effective_category(revit_cat, family_name, type_name)

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

    records.append({
        'eid': eid,
        'revit_cat': revit_cat,
        'eff_cat': eff_cat,
        'level_name': level_name,
        'phase_created': phase_created,
        'family_name': family_name,
        'type_name': type_name,
        'zmin': zmin,
        'eff_priority': eff_priority,
        'zone_id': None
    })

# Assign zones
zone_bounds, element_zone_map, zone_stats = compute_zone_grid_and_assign(elements, grid_cell_size)

for r in records:
    eid = r['eid']
    r['zone_id'] = element_zone_map.get(eid, "UNZONED")

# Sort by zone, then within zone
def get_zone_coords(zone_id):
    if zone_id == "UNZONED":
        return (999, 999)
    parts = zone_id.split("_")
    try:
        return (int(parts[1]), int(parts[2]))
    except:
        return (999, 999)

records.sort(key=lambda r: (get_zone_coords(r['zone_id']), r['zmin'], r['eff_priority'], safe_int(r['eid'])))

# Compute sequence order per zone
seq_in_zone = {}
zone_seq_counters = {}
for r in records:
    zone_id = r['zone_id']
    if zone_id not in zone_seq_counters:
        zone_seq_counters[zone_id] = 0
    zone_seq_counters[zone_id] += 1
    seq_in_zone[r['eid']] = zone_seq_counters[zone_id]

# Validation
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
    
    records_by_zone = {}
    for idx, r in enumerate(records):
        zone_id = r['zone_id']
        if zone_id not in records_by_zone:
            records_by_zone[zone_id] = []
        records_by_zone[zone_id].append((idx, r))
    
    for zone_id in sorted(records_by_zone.keys()):
        zone_records = records_by_zone[zone_id]
        
        cat_indices = {}
        for idx, r in zone_records:
            eff_cat = r['eff_cat']
            if eff_cat not in cat_indices:
                cat_indices[eff_cat] = []
            cat_indices[eff_cat].append(idx)
        
        for earlier_cat, later_cat in precedence_rules:
            if earlier_cat not in cat_indices or later_cat not in cat_indices:
                continue
            
            max_earlier_idx = max(cat_indices[earlier_cat])
            min_later_idx = min(cat_indices[later_cat])
            
            if max_earlier_idx > min_later_idx:
                violations.append({
                    'zone_id': zone_id,
                    'rule': "{} before {}".format(earlier_cat, later_cat),
                    'later_idx': min_later_idx,
                    'earlier_idx': max_earlier_idx,
                    'later_element': records[min_later_idx],
                    'earlier_element': records[max_earlier_idx]
                })

# ===== NEW (Iteration 4): Build Dependency Graph =====

# NEW: Create action nodes for each (zone, category) pair
action_nodes = {}  # key: (zone_id, eff_cat), value: action_id
action_counter = 0
zone_cat_pairs = set()

for r in records:
    zone_id = r['zone_id']
    eff_cat = r['eff_cat']
    pair = (zone_id, eff_cat)
    
    if pair not in zone_cat_pairs:
        zone_cat_pairs.add(pair)
        action_id = "A_{}".format(action_counter)
        action_nodes[pair] = {
            'id': action_id,
            'zone': zone_id,
            'category': eff_cat,
            'label': "{}_{}".format(zone_id, eff_cat),
            'element_count': 0
        }
        action_counter += 1

# Count elements per action
for r in records:
    zone_id = r['zone_id']
    eff_cat = r['eff_cat']
    pair = (zone_id, eff_cat)
    if pair in action_nodes:
        action_nodes[pair]['element_count'] += 1

# NEW: Define precedence edges
edges = []
precedence_rules_graph = [
    ("FOOTING", "COLUMN"),
    ("FOOTING", "BEAM"),
    ("FOOTING", "SLAB"),
    ("COLUMN", "BEAM"),
    ("COLUMN", "SLAB"),
    ("BEAM", "SLAB"),
]

# Within-zone dependencies (construction logic)
for zone_id in sorted(zone_stats.keys()):
    zone_action_keys = [pair for pair in action_nodes.keys() if pair[0] == zone_id]
    
    for earlier_cat, later_cat in precedence_rules_graph:
        source_key = (zone_id, earlier_cat)
        target_key = (zone_id, later_cat)
        
        if source_key in action_nodes and target_key in action_nodes:
            source_id = action_nodes[source_key]['id']
            target_id = action_nodes[target_key]['id']
            edges.append({
                'source': source_id,
                'target': target_id,
                'type': 'precedence',
                'description': '{} before {} in {}'.format(earlier_cat, later_cat, zone_id)
            })

# Between-zone dependencies (zone sequence: left-to-right, bottom-to-top)
# For each category, create sequential dependency across zones
zone_list = sorted(zone_stats.keys(), key=lambda z: get_zone_coords(z))

for i in range(len(zone_list) - 1):
    zone_a = zone_list[i]
    zone_b = zone_list[i + 1]
    
    # Within each category, Zone A must complete before Zone B
    for cat in set([pair[1] for pair in action_nodes.keys()]):
        source_key = (zone_a, cat)
        target_key = (zone_b, cat)
        
        if source_key in action_nodes and target_key in action_nodes:
            source_id = action_nodes[source_key]['id']
            target_id = action_nodes[target_key]['id']
            edges.append({
                'source': source_id,
                'target': target_id,
                'type': 'zone_sequence',
                'description': '{} in {} before {} in {}'.format(cat, zone_a, cat, zone_b)
            })

# NEW: Export graph as JSON
graph_data = {
    'graph_type': 'DAG (Directed Acyclic Graph)',
    'methodology': 'Iteration 4 - Dependency Graph',
    'nodes': list(action_nodes.values()),
    'edges': edges,
    'metadata': {
        'total_elements': len(elements),
        'total_zones': len(zone_stats),
        'total_actions': len(action_nodes),
        'total_dependencies': len(edges),
        'grid_cell_size': grid_cell_size
    }
}

# Write graph JSON
path_base = path.rsplit(".", 1)[0] if "." in path else path
json_path = path_base + "_graph.json"

def esc(v):
    if v is None:
        return ""
    s = str(v).replace('"', '""')
    if ("," in s) or ("\n" in s) or ("\r" in s):
        s = '"' + s + '"'
    return s

# Write sequence CSV
rows = []
rows.append(["sequence_order", "element_id", "effective_category", "zone_id", "seq_in_zone",
             "revit_category", "level_name", "phase_created", "family_name", "type_name"])

for idx, r in enumerate(records):
    rows.append([
        idx + 1,
        r['eid'],
        r['eff_cat'],
        r['zone_id'],
        seq_in_zone.get(r['eid'], ''),
        r['revit_cat'],
        r['level_name'],
        r['phase_created'],
        r['family_name'],
        r['type_name']
    ])

folder = System.IO.Path.GetDirectoryName(path)
if folder and not Directory.Exists(folder):
    Directory.CreateDirectory(folder)

# Write CSV
lines = []
for r in rows:
    lines.append(",".join([esc(x) for x in r]))

File.WriteAllLines(path, lines)

# Write JSON graph
json_str = json.dumps(graph_data, indent=2)
File.WriteAllText(json_path, json_str)

# Build output message
output_msg = "Iteration 4 - Dependency Graph Representation\n"
output_msg += "Elements: {}\n".format(len(elements))
output_msg += "Zones: {}\n".format(len(zone_stats))
output_msg += "Actions (zone-category pairs): {}\n".format(len(action_nodes))
output_msg += "Dependencies: {}\n".format(len(edges))
output_msg += "\nFiles written:\n"
output_msg += "  CSV sequence: {}\n".format(path)
output_msg += "  JSON graph: {}\n".format(json_path)

output_msg += "\nGraph Summary:\n"
output_msg += "  Within-zone precedence edges: {}\n".format(
    len([e for e in edges if e['type'] == 'precedence'])
)
output_msg += "  Between-zone sequence edges: {}\n".format(
    len([e for e in edges if e['type'] == 'zone_sequence'])
)

if enable_validation:
    output_msg += "\nValidation Results:\n"
    if violations:
        output_msg += "  VIOLATIONS: {} precedence rule(s) violated\n".format(len(violations))
    else:
        output_msg += "  PASS: All precedence rules satisfied.\n"

output_msg += "\nActions (Zone-Category Pairs):\n"
for pair, action in sorted(action_nodes.items()):
    output_msg += "  {}: {} elements\n".format(action['label'], action['element_count'])

OUT = output_msg
