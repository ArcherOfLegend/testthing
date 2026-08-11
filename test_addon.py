import bpy, sys, os, hashlib, struct

# Resolve everything relative to this script so the toolkit can live anywhere.
# --python strips argv, so fall back to cwd if __file__ is unavailable.
try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
SP    = TOOLS
SRC   = os.path.join(SP, "extracted", "ui", "chs", "chs_meku", "chs_meku.mod")
OUT   = os.path.join(SP, "chs_meku_roundtrip.mod")
OUT2  = os.path.join(SP, "chs_meku_edited.mod")

sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

bpy.ops.wm.read_factory_settings(use_empty=True)

print("=== IMPORT ===")
n = M.import_mod(bpy.context, SRC, 0.01)
print("meshes imported:", n)

objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print("mesh objects:", len(objs))
tot_v = sum(len(o.data.vertices) for o in objs)
tot_f = sum(len(o.data.polygons) for o in objs)
print("total verts:", tot_v, " total tris:", tot_f)
textured = 0
for o in sorted(objs, key=lambda x: x["umvc3_mesh_index"]):
    uv = "yes" if o.data.uv_layers.active else "no "
    matname, imgname = "<none>", "<none>"
    if o.data.materials and o.data.materials[0]:
        mat = o.data.materials[0]
        matname = mat.name
        if mat.use_nodes:
            for nd in mat.node_tree.nodes:
                if nd.type == "TEX_IMAGE" and nd.image:
                    imgname = "%s %dx%d" % (nd.image.name, nd.image.size[0], nd.image.size[1])
                    if nd.image.size[0] > 0:
                        textured += 1
    print("  %-8s mat=%-2s verts=%-5d tris=%-5d uv=%s  %-20s %s" %
          (o.name, o["umvc3_material"], len(o.data.vertices), len(o.data.polygons), uv, matname, imgname))
print("meshes with a loaded texture image:", textured, "/", len(objs))

print("=== EXPORT (no edits) ===")
nm, clamped = M.export_mod(bpy.context, OUT, SRC, 0.01, True, True, False)
print("meshes exported:", nm, "clamped:", clamped)

a, b = sha(SRC), sha(OUT)
print("src :", a)
print("out :", b)
print("BIT-IDENTICAL ROUND-TRIP:", a == b)

if a != b:
    da = open(SRC, "rb").read(); db = open(OUT, "rb").read()
    print("len", len(da), len(db))
    diffs = [i for i in range(min(len(da), len(db))) if da[i] != db[i]]
    print("differing bytes:", len(diffs), "first:", diffs[:12])

print("=== EXPORT (with an edit) ===")
# nudge every vertex of mesh 7 up by 0.1 blender units (=10 game units)
tgt = [o for o in objs if o["umvc3_mesh_index"] == 7][0]
for v in tgt.data.vertices:
    v.co.y += 0.1
nm, clamped = M.export_mod(bpy.context, OUT2, SRC, 0.01, True, True, False)
print("exported, clamped:", clamped)

de = open(OUT2, "rb").read(); do = open(SRC, "rb").read()
print("same length:", len(de) == len(do))
diffs = [i for i in range(len(do)) if do[i] != de[i]]
print("bytes changed by the edit:", len(diffs))
if diffs:
    vtx_off = struct.unpack_from("<Q", do, 0x48)[0]
    idx_off = struct.unpack_from("<Q", do, 0x50)[0]
    print("first changed offset: 0x%X   vertexBuffer starts 0x%X, indexBuffer 0x%X"
          % (diffs[0], vtx_off, idx_off))
    inside = all(vtx_off <= d < idx_off for d in diffs)
    print("ALL CHANGES CONFINED TO VERTEX BUFFER:", inside)
