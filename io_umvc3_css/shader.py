"""Turn a Blender material's Base Color graph into a ps_3_0 pixel shader.

Why hand-written rather than routed through an interchange format: Blender ships
MaterialX 1.39 core only - the document model, with no shader generators - and a
GLSL route would then need glslang and SPIRV-Cross, neither of which is here,
and would finally have to downcompile Shader Model 4+ output to ps_3_0. That
last step is the one that kills it. The shader this replaces is 768 bytes of
ps_3_0: 224 constant registers, 16 samplers, no integer ops, no real branching.
Generated PBR code does not survive that budget, and a translator that emits for
the target directly always will.

The contract comes from disassembling the shader being replaced, so the
substitute consumes exactly what the game's vertex shader emits:

    sampler2D SSAlbedoMap__tAlbedoMap   s0     the material's bound texture
    dcl_texcoord  v0                           interpolated colour, .w used as alpha
    dcl_texcoord1 v1.w
    dcl_texcoord2 v2.xy                        the uv

Registers are pinned with `: register(...)` rather than left to fxc, which
assigns by declaration order - and the game fills those registers by its own
numbering, so drifting off it samples whatever happens to be in s0.

Supported nodes are deliberately few. Every one of them is something the game
can evaluate per pixel, which is the whole point: baking collapses a graph to
one averaged colour, this keeps it live.
"""
import re

# --------------------------------------------------------------------------
# The subset. Anything outside it is reported by name rather than silently
# emitting something plausible - a shader that compiles but shades wrongly is
# far more expensive to debug than one that refuses to build.
SUPPORTED = {
    "TEX_IMAGE", "RGB", "VALUE", "MIX_RGB", "MIX", "MATH", "VECTOR_MATH",
    "INVERT", "BRIGHTCONTRAST", "GAMMA", "HUE_SAT", "SEPARATE_COLOR",
    "COMBINE_COLOR", "REROUTE", "TEX_COORD", "UVMAP", "SEPXYZ", "VALTORGB",
}

# Below this the halo contributes nothing visible but still writes depth.
ALPHA_CLIP = 0.02

MATH_OPS = {
    "ADD": "({a} + {b})", "SUBTRACT": "({a} - {b})", "MULTIPLY": "({a} * {b})",
    "DIVIDE": "({a} / max({b}, 1e-6))", "POWER": "pow(max({a}, 0.0), {b})",
    "MINIMUM": "min({a}, {b})", "MAXIMUM": "max({a}, {b})",
    "ABSOLUTE": "abs({a})", "SQRT": "sqrt(max({a}, 0.0))",
    "FRACT": "frac({a})", "SINE": "sin({a})", "COSINE": "cos({a})",
    "ROUND": "round({a})", "FLOOR": "floor({a})", "CEIL": "ceil({a})",
    "GREATER_THAN": "step({b}, {a})", "LESS_THAN": "step({a}, {b})",
}

HEADER = """// Generated from the Blender material %(name)s by io_umvc3_css.
// Target ps_3_0; register assignments taken from the shader being replaced.
sampler2D tAlbedo : register(s0);

struct PSIn {
    float4 vcol : TEXCOORD0;   // .w carries the interpolated alpha
    float4 aux  : TEXCOORD1;
    float2 uv   : TEXCOORD2;
};

float4 main(PSIn psin) : COLOR
{
"""

FOOTER = """    return float4(%(result)s, %(alpha)s);
}
"""


class Unsupported(Exception):
    pass


def _ident(node):
    return "n_" + re.sub(r"[^0-9A-Za-z_]", "_", node.name)


def _lit(v):
    try:
        seq = list(v)
    except TypeError:
        return "%.6f" % float(v)
    if len(seq) >= 3:
        return "float3(%.6f, %.6f, %.6f)" % (seq[0], seq[1], seq[2])
    return "%.6f" % float(seq[0])


def _follow(inp):
    """The node feeding a socket, through reroutes."""
    n = 0
    while inp is not None and inp.is_linked and n < 32:
        node = inp.links[0].from_node
        if node.type != "REROUTE":
            return node, inp.links[0].from_socket
        inp = node.inputs[0]
        n += 1
    return None, None


class Emitter(object):
    def __init__(self, mat):
        self.mat = mat
        self.lines = []
        self.done = {}
        self.notes = []

    # each emit_* returns an HLSL expression of type float3
    def value_of(self, socket):
        node, from_sock = _follow(socket)
        if node is None:
            return _lit(getattr(socket, "default_value", 0.0))
        return self.emit(node, from_sock)

    def scalar_of(self, socket):
        node, from_sock = _follow(socket)
        if node is None:
            v = getattr(socket, "default_value", 0.0)
            try:
                return "%.6f" % float(v)
            except TypeError:
                return "%.6f" % float(list(v)[0])
        expr = self.emit(node, from_sock)
        return expr if expr.startswith("dot(") or "." in expr[-3:] else "(%s).x" % expr

    def emit(self, node, from_sock=None):
        if node.type not in SUPPORTED:
            raise Unsupported(node.type)
        key = (node.name, getattr(from_sock, "name", ""))
        if key in self.done:
            return self.done[key]
        name = _ident(node)
        if from_sock is not None and getattr(from_sock, "name", ""):
            name += "_" + re.sub(r"[^0-9A-Za-z_]", "", from_sock.name)

        t = node.type
        if t == "TEX_IMAGE":
            # The game binds the material's texture to s0. Which image is shown
            # in Blender does not travel here - the MRL binding decides that, and
            # export rebinds it separately.
            self.lines.append("    float4 %s_t = tex2D(tAlbedo, psin.uv);" % name)
            expr = "%s_t.rgb" % name
            if from_sock is not None and from_sock.name == "Alpha":
                expr = "%s_t.aaa" % name
        elif t == "RGB":
            expr = _lit(node.outputs[0].default_value)
        elif t == "VALUE":
            v = "%.6f" % float(node.outputs[0].default_value)
            expr = "float3(%s, %s, %s)" % (v, v, v)
        elif t in ("MIX_RGB", "MIX"):
            fac = self.scalar_of(node.inputs.get("Fac") or node.inputs.get("Factor")
                                 or node.inputs[0])
            ins = [s for s in node.inputs if s.type in ("RGBA", "VECTOR", "VALUE")]
            cols = [s for s in node.inputs if s.type == "RGBA"] or ins[-2:]
            a = self.value_of(cols[-2])
            b = self.value_of(cols[-1])
            blend = getattr(node, "blend_type", "MIX")
            if blend == "MULTIPLY":
                expr = "lerp(%s, %s * %s, saturate(%s))" % (a, a, b, fac)
            elif blend == "ADD":
                expr = "lerp(%s, %s + %s, saturate(%s))" % (a, a, b, fac)
            elif blend == "SUBTRACT":
                expr = "lerp(%s, %s - %s, saturate(%s))" % (a, a, b, fac)
            elif blend == "SCREEN":
                expr = "lerp(%s, 1.0 - (1.0 - %s) * (1.0 - %s), saturate(%s))" % (a, a, b, fac)
            else:
                expr = "lerp(%s, %s, saturate(%s))" % (a, b, fac)
        elif t == "MATH":
            op = node.operation
            if op not in MATH_OPS:
                raise Unsupported("MATH:" + op)
            a = self.scalar_of(node.inputs[0])
            b = self.scalar_of(node.inputs[1]) if len(node.inputs) > 1 else "0.0"
            s = MATH_OPS[op].format(a=a, b=b)
            expr = "float3(%s, %s, %s)" % (s, s, s)
        elif t == "VECTOR_MATH":
            op = node.operation
            if op not in MATH_OPS:
                raise Unsupported("VECTOR_MATH:" + op)
            a = self.value_of(node.inputs[0])
            b = self.value_of(node.inputs[1]) if len(node.inputs) > 1 else "0.0"
            expr = MATH_OPS[op].format(a=a, b=b)
        elif t == "INVERT":
            fac = self.scalar_of(node.inputs[0])
            col = self.value_of(node.inputs[1])
            expr = "lerp(%s, 1.0 - %s, saturate(%s))" % (col, col, fac)
        elif t == "GAMMA":
            col = self.value_of(node.inputs[0])
            g = self.scalar_of(node.inputs[1])
            expr = "pow(max(%s, 0.0), %s)" % (col, g)
        elif t == "BRIGHTCONTRAST":
            col = self.value_of(node.inputs[0])
            br = self.scalar_of(node.inputs[1])
            ct = self.scalar_of(node.inputs[2])
            expr = "saturate((%s - 0.5) * (1.0 + %s) + 0.5 + %s)" % (col, ct, br)
        elif t == "HUE_SAT":
            # Saturation and value only: a hue rotation costs a matrix this
            # budget does not need to spend, and it is reported rather than
            # silently ignored.
            col = self.value_of(node.inputs.get("Color") or node.inputs[-1])
            sat = self.scalar_of(node.inputs["Saturation"]) if "Saturation" in node.inputs else "1.0"
            val = self.scalar_of(node.inputs["Value"]) if "Value" in node.inputs else "1.0"
            self.notes.append("%s: hue rotation is not emitted, saturation and value are"
                              % node.name)
            self.lines.append("    float %s_l = dot(%s, float3(0.2126, 0.7152, 0.0722));"
                              % (name, col))
            expr = "lerp(float3(%s_l, %s_l, %s_l), %s, %s) * %s" % (name, name, name, col, sat, val)
        elif t == "SEPARATE_COLOR":
            col = self.value_of(node.inputs[0])
            ch = {"Red": "r", "Green": "g", "Blue": "b"}.get(
                getattr(from_sock, "name", "Red"), "r")
            self.lines.append("    float3 %s_c = %s;" % (name, col))
            expr = "%s_c.%s%s%s" % (name, ch, ch, ch)
        elif t in ("TEX_COORD", "UVMAP"):
            # The mesh's own uv. On the grid lines it runs across the ribbon, so
            # this is what a falloff is measured along.
            expr = "float3(psin.uv, 0.0)"
        elif t == "SEPXYZ":
            v = self.value_of(node.inputs[0])
            ch = {"X": "x", "Y": "y", "Z": "z"}.get(getattr(from_sock, "name", "X"), "x")
            self.lines.append("    float3 %s_v = %s;" % (name, v))
            expr = "%s_v.%s%s%s" % (name, ch, ch, ch)
        elif t == "VALTORGB":
            # A ColorRamp becomes nested lerps between its stops - the natural
            # way to author a falloff, and cheap enough that ps_3_0 does not
            # care. CONSTANT interpolation becomes steps instead.
            ramp = node.color_ramp
            els = sorted(ramp.elements, key=lambda e: e.position)
            fac = self.scalar_of(node.inputs[0])
            self.lines.append("    float %s_f = saturate(%s);" % (name, fac))
            wants_alpha = getattr(from_sock, "name", "Color") == "Alpha"

            def chan(e):
                c = list(e.color)
                return ("%.6f" % c[3]) if wants_alpha else \
                       "float3(%.6f, %.6f, %.6f)" % (c[0], c[1], c[2])

            if not els:
                expr = "0.0" if wants_alpha else "float3(0.0, 0.0, 0.0)"
            else:
                acc = chan(els[0])
                for a, b in zip(els, els[1:]):
                    span = max(b.position - a.position, 1e-6)
                    tt = "saturate((%s_f - %.6f) / %.6f)" % (name, a.position, span)
                    if ramp.interpolation == "CONSTANT":
                        tt = "step(%.6f, %s_f)" % (b.position, name)
                    acc = "lerp(%s, %s, %s)" % (acc, chan(b), tt)
                expr = acc
            if wants_alpha:
                expr = "float3(%s, %s, %s)" % (expr, expr, expr)
        elif t == "COMBINE_COLOR":
            r = self.scalar_of(node.inputs[0])
            g = self.scalar_of(node.inputs[1])
            b = self.scalar_of(node.inputs[2])
            expr = "float3(%s, %s, %s)" % (r, g, b)
        else:
            raise Unsupported(t)

        self.lines.append("    float3 %s = %s;" % (name, expr))
        self.done[key] = name
        return name


def emit_hlsl(mat, base_input, alpha_input=None):
    """(hlsl source, notes) for a material, or raises Unsupported.

    `base_input` is the Base Color socket; everything reachable from it is
    translated. If the BSDF's Alpha socket is linked it is translated too and
    drives the output alpha - which is what makes a glow possible at all, since
    a laser fades by going transparent, not by going black. Left unlinked, alpha
    stays on the interpolated vertex colour, as the original shader had it.
    """
    em = Emitter(mat)
    node, sock = _follow(base_input)
    if node is None:
        result = _lit(getattr(base_input, "default_value", (0.8, 0.8, 0.8)))
    else:
        result = em.emit(node, sock)
    alpha = "psin.vcol.w"
    if alpha_input is not None and alpha_input.is_linked:
        alpha = "saturate(%s) * psin.vcol.w" % em.scalar_of(alpha_input)
        # Kill the near-invisible outskirts of the halo. Blending them is
        # harmless, but they still write depth across the ribbon's full width,
        # so anything crossing behind gets clipped by a part of the glow nobody
        # can see - lines vanishing where they pass through another line's halo.
        # texkill is what the original shader used for the same reason.
        em.lines.append("    float _a = %s;" % alpha)
        em.lines.append("    clip(_a - %.4f);" % ALPHA_CLIP)
        alpha = "_a"
    src = HEADER % {"name": mat.name}
    src += "\n".join(em.lines)
    if em.lines:
        src += "\n"
    src += FOOTER % {"result": result, "alpha": alpha}
    return src, em.notes


# ===================================================== graph round trip =====
# The authored graph IS the shader, so it has to survive a re-import. Without
# this, importing rebuilds the stock image -> Principled -> Output stub and any
# graph you wrote is gone; you would author the glow once and then rebuild it by
# hand every session.
#
# Saved beside the .hlsl and .bin it generated, so a shader and its source graph
# travel together and neither can go stale against the other.
GRAPH_VERSION = 1
_SAVE_NODES = SUPPORTED | {"BSDF_PRINCIPLED", "OUTPUT_MATERIAL"}


def _sock_value(s):
    v = getattr(s, "default_value", None)
    if v is None:
        return None
    try:
        return [float(x) for x in v]
    except TypeError:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


def graph_to_dict(mat):
    """The material's node graph as plain data, for the subset we translate."""
    nt = mat.node_tree
    if nt is None:
        return None
    nodes, links = [], []
    for n in nt.nodes:
        if n.type not in _SAVE_NODES:
            continue
        rec = {"name": n.name, "type": n.bl_idname,
               "loc": [n.location.x, n.location.y], "inputs": {}}
        for s in n.inputs:
            if not s.is_linked:
                val = _sock_value(s)
                if val is not None:
                    rec["inputs"][s.identifier] = val
        if n.type == "TEX_IMAGE":
            rec["image"] = getattr(n.image, "name", None)
            rec["entry"] = n.image.get("umvc3_entry") if n.image else None
        if hasattr(n, "blend_type"):
            rec["blend_type"] = n.blend_type
        if hasattr(n, "operation"):
            rec["operation"] = n.operation
        if n.type == "VALTORGB":
            rec["ramp"] = {
                "interpolation": n.color_ramp.interpolation,
                "elements": [{"position": e.position, "color": list(e.color)}
                             for e in n.color_ramp.elements],
            }
        if n.type in ("RGB", "VALUE"):
            rec["output"] = _sock_value(n.outputs[0])
        nodes.append(rec)
    keep = {n["name"] for n in nodes}
    for l in nt.links:
        if l.from_node.name in keep and l.to_node.name in keep:
            links.append([l.from_node.name, l.from_socket.identifier,
                          l.to_node.name, l.to_socket.identifier])
    return {"version": GRAPH_VERSION, "material": mat.name,
            "crc": mat.get("umvc3_shader_crc"), "nodes": nodes, "links": links}


def graph_from_dict(mat, data, find_image=None):
    """Rebuild a saved graph onto a material. Returns a list of notes."""
    if not data or data.get("version") != GRAPH_VERSION:
        return ["graph was written by a different version, ignored"]
    nt = mat.node_tree
    notes = []
    nt.nodes.clear()
    made = {}
    for rec in data["nodes"]:
        try:
            n = nt.nodes.new(rec["type"])
        except RuntimeError:
            notes.append("this Blender has no %s node" % rec["type"])
            continue
        n.name = rec["name"]
        n.location = rec.get("loc", (0, 0))
        made[rec["name"]] = n
        if rec.get("blend_type") and hasattr(n, "blend_type"):
            n.blend_type = rec["blend_type"]
        if rec.get("operation") and hasattr(n, "operation"):
            n.operation = rec["operation"]
        if rec.get("ramp") and n.type == "VALTORGB":
            r = n.color_ramp
            els = rec["ramp"]["elements"]
            # A fresh ramp comes with two stops that cannot be removed, so fill
            # those before adding, and remove nothing.
            for i, e in enumerate(els):
                el = r.elements[i] if i < len(r.elements) else r.elements.new(e["position"])
                el.position = e["position"]
                el.color = e["color"]
            r.interpolation = rec["ramp"]["interpolation"]
        if n.type == "TEX_IMAGE" and rec.get("image") and find_image:
            n.image = find_image(rec.get("entry"), rec["image"])
        if rec.get("output") is not None and n.type in ("RGB", "VALUE"):
            try:
                n.outputs[0].default_value = rec["output"]
            except (TypeError, ValueError):
                pass
        for ident, val in (rec.get("inputs") or {}).items():
            s = n.inputs.get(ident)
            if s is None:
                continue
            try:
                s.default_value = val
            except (TypeError, ValueError):
                pass
    for a, asock, b, bsock in data["links"]:
        fn, tn = made.get(a), made.get(b)
        if not fn or not tn:
            continue
        fs, ts = fn.outputs.get(asock), tn.inputs.get(bsock)
        if fs and ts:
            nt.links.new(ts, fs)
    if data.get("crc"):
        mat["umvc3_shader_crc"] = data["crc"]
    return notes


def unsupported_nodes(base_input):
    """Every node reachable from Base Color that this cannot translate, so the
    UI can say so before an export rather than after a failed compile."""
    bad, seen = [], set()
    stack = []
    node, _ = _follow(base_input)
    if node is not None:
        stack.append(node)
    while stack:
        n = stack.pop()
        if n.name in seen:
            continue
        seen.add(n.name)
        if n.type not in SUPPORTED:
            bad.append((n.name, n.type))
            continue
        if n.type == "MATH" and n.operation not in MATH_OPS:
            bad.append((n.name, "MATH:" + n.operation))
        for s in n.inputs:
            f, _ = _follow(s)
            if f is not None:
                stack.append(f)
    return bad
