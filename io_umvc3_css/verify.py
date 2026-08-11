"""Pre-install checks on a built archive.

Every one of these caught a real bug at some point, so none of them is
ceremony:

Hard problems - these mean the archive is wrong:

  1 every card material's stored joint id matches its name - renaming without
    rewriting bits 21..28 changes nothing the engine reads
  2 mesh -> .mrl bindings resolve one-to-one - an in-place rename pass once
    scrambled 249 of them silently
  3 no two cards claim the same cell, and none is outside the grid
  4 skin weights sum to 1 and name bones that exist

Warnings - the grid is not laid out on a regular lattice any more. That is a
mistake if it happened by accident and the whole point if it did not, so a
deliberately rearranged screen reports these and still installs:

  5 one x per column, one y per row, row centres descending

The positional tolerance is 5 units, not 2: the `selr1` hover frames are
deliberately jittered and stock itself trips a tighter bound.
"""
import struct

from . import mod as M
from . import grid as G

TOL = 5.0

# A card is a flat quad lying on the paper. Its z range is only the page's local
# tilt, which is about 25 units at the very most across a stock card. Anything
# beyond this is not a tilt, it is a fold: it means per-vertex depth came from
# somewhere that was extrapolating, and the card renders as a spike. One card
# dragged just past the spine reached 5919 units this way.
FLAT_LIMIT = 100.0


def verify_archive(entries, rows, cols_per_page, stock_entries=None, stock_rows=None):
    """-> (problems, warnings, per-model report lines).

    `stock_rows` is the row count the *reference* archive numbers its joint ids
    with - 7 for a vanilla one, but the same as `rows` when checking against
    another built archive. Get it wrong and the drift column compares two
    different cells and reports hundreds of units for an untouched export, so it
    is detected from the reference rather than assumed."""
    problems, warnings, lines = [], [], []
    stock = {e.name: e for e in (stock_entries or [])}
    if stock_entries and not stock_rows:
        stock_rows = G.detect_grid(stock_entries)[0]
    stock_rows = stock_rows or G.SRC_ROWS

    def check(cond, msg):
        if not cond:
            problems.append(msg)

    def warn(cond, msg):
        if not cond:
            warnings.append(msg)

    by = {}
    for e in entries:
        by.setdefault(e.name, {})[e.ext] = e

    for name in sorted(by):
        x = by[name]
        short = G.leaf(name)
        if not G.model_kind(name) or "mod" not in x or "mrl" not in x:
            continue
        b, mrl = x["mod"].data, x["mrl"].data
        q = M.model_dequant(b)
        names = M.read_mod_material_names(b)
        nbones = M._u16(b, 0x06)
        vert_off = M._u64(b, M.H_VERTOFF)
        n_mrl, moff = M._u32(mrl, 8), M._u64(mrl, 32)

        hash_to_entry = {}
        for j in range(n_mrl):
            h = M._u32(mrl, moff + j * M.MRL_ENT + 8)
            check(h not in hash_to_entry, "%s: duplicate .mrl hash %08X" % (short, h))
            hash_to_entry[h] = j

        cells, cols_x, rows_y = {}, {}, {}
        for m in M.read_meshes(b):
            nm = names[m["material"]]
            g = G.MAT_ID.match(nm)
            j = hash_to_entry.get(M.mt_hash(nm))
            check(j is not None,
                  "%s: mesh %d material %r has no .mrl entry" % (short, m["index"], nm))
            if g is None or j is None:
                continue
            jid = int(g.group(2))
            stored = G.read_joint_id(mrl, j)
            check(stored == jid,
                  "%s: %s stores joint id %d, name says %d" % (short, nm, stored, jid))
            col, row = G.cell_of_jid(jid, rows)
            check(0 <= col < cols_per_page and 0 <= row < rows,
                  "%s: joint id %d is outside a %d x %d grid"
                  % (short, jid, rows, cols_per_page))
            check((col, row) not in cells,
                  "%s: two cards claim cell (%d,%d)" % (short, col, row))

            pts = []
            for k in range(m["nverts"]):
                vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
                pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
                w = M.read_skin(b, vo)
                total = sum(w.values())
                check(abs(total - 1.0) < 1e-3,
                      "%s: mesh %d vertex %d weights sum to %.4f"
                      % (short, m["index"], k, total))
                check(all(0 <= i < nbones for i in w),
                      "%s: mesh %d vertex %d references a bone outside 0..%d"
                      % (short, m["index"], k, nbones - 1))
            zspread = max(p[2] for p in pts) - min(p[2] for p in pts)
            check(zspread <= FLAT_LIMIT,
                  "%s: card %d (joint id %d) spans %.0f units in z - a card is "
                  "flat, so its depth came from a surface that was extrapolating"
                  % (short, m["index"], jid, zspread))
            cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
            cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
            cells[(col, row)] = {"mesh": m["index"], "cx": cx, "cy": cy, "jid": jid}
            if row > 0:
                cols_x.setdefault(col, []).append(cx)
            rows_y.setdefault(row, []).append(cy)

        for col, v in cols_x.items():
            warn(max(v) - min(v) < TOL,
                 "%s: column %d spans x %.1f..%.1f, cards are not aligned"
                 % (short, col, min(v), max(v)))
        for row, v in rows_y.items():
            if row == 0:                       # shares its row with the banner
                continue
            warn(max(v) - min(v) < TOL,
                 "%s: row %d spans y %.1f..%.1f, cards are not aligned"
                 % (short, row, min(v), max(v)))
        ys = [sum(rows_y[r]) / len(rows_y[r]) for r in sorted(rows_y)]
        warn(all(ys[i] > ys[i + 1] for i in range(len(ys) - 1)),
             "%s: row centres are not monotonically descending: %s"
             % (short, [round(v, 1) for v in ys]))

        drift = 0.0
        se = stock.get(name)
        if se is not None:
            sb = se.data
            sq = M.model_dequant(sb)
            snames = M.read_mod_material_names(sb)
            svert = M._u64(sb, M.H_VERTOFF)
            smesh = {}
            for m in M.read_meshes(sb):
                g = G.MAT_ID.match(snames[m["material"]])
                if g:
                    jid = int(g.group(2))
                    smesh[G.cell_of_jid(jid, stock_rows)] = m
            live = {m["index"]: m for m in M.read_meshes(b)}
            for cell_key, sm in smesh.items():
                cell = cells.get(cell_key)
                if cell is None:
                    continue
                nm2 = live[cell["mesh"]]
                if nm2["nverts"] != sm["nverts"]:
                    continue
                for k in range(sm["nverts"]):
                    so = svert + sm["vbufoff"] + (sm["vtxlo"] + k) * sm["stride"]
                    no = vert_off + nm2["vbufoff"] + (nm2["vtxlo"] + k) * nm2["stride"]
                    sp = sq.decode(struct.unpack_from("<3H", sb, so))
                    np_ = q.decode(struct.unpack_from("<3H", b, no))
                    drift = max(drift, max(abs(sp[i] - np_[i]) for i in range(3)))

        missing = [(c, r) for c in range(cols_per_page) for r in range(1, rows)
                   if (c, r) not in cells]
        lines.append("%-26s %3d cards  %3d free cells  step %.4f  drift %.4f%s"
                     % (short, len(cells), len(missing), q.scale / M.POS_SCALE, drift,
                        ("  MISSING %s" % missing[:6]) if missing else ""))
    return problems, warnings, lines


def verify_file(path, rows, cols_per_page, stock_path=None, stock_rows=None):
    _, entries = M.read_arc(path)
    stock = None
    if stock_path:
        _, stock = M.read_arc(stock_path)
    return verify_archive(entries, rows, cols_per_page, stock, stock_rows)
