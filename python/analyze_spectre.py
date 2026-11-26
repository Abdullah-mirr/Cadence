"""
Post-processing for the spectre runs.
Reads results/<bench>.raw (psfascii), writes csv tables, summary.txt,
checks.txt and the plots.

    python3 python/analyze_spectre.py            # everything
    python3 python/analyze_spectre.py --cs-bias  # only the CS amp bias point

Plots need matplotlib, the rest is plain python.
"""
import csv
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
PLOTS = os.path.join(ROOT, "plots")
SPECTRE_DIR = os.path.join(ROOT, "spectre")

VSUP = 1.2            # supply used in the test benches (V)
AC_FREQ = 100e6       # fixed frequency of the ac parameter sweeps (Hz)
WN = 1e-6             # NMOS width in gm_id_sweep.scs (m)
WP = 1e-6             # PMOS width in pmos_iv.scs (m)
LENGTHS = ["060", "170", "280", "390", "500"]   # nm, as in gm_id_sweep.scs
RL = 10e3             # load resistor in cs_amplifier.scs (ohm)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_PLT = True
except Exception:
    HAVE_PLT = False

summary_lines = []
found = {}          # key results, used by run_checks()


def say(text=""):
    print(text)
    summary_lines.append(text)


# 1. PSF ASCII reader
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+')
_SECTIONS = {"HEADER", "TYPE", "SWEEP", "TRACE", "VALUE", "END"}


def _tokens(text):
    for m in _TOKEN.finditer(text):
        yield m.group(0)


def _is_str(tok):
    return len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"'


def _unq(tok):
    return tok[1:-1]


def _num(tok):
    try:
        return float(tok)
    except ValueError:
        return None


class _Stream:
    def __init__(self, toks):
        self.t = list(toks)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def skip_block(self):
        """skip a balanced ( ... ) block, the '(' is the next token"""
        depth = 0
        while self.peek() is not None:
            tok = self.next()
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                if depth == 0:
                    return

    def read_value(self):
        """a number, or a ( ... ) list of values (nested lists allowed)"""
        tok = self.next()
        if tok == "(":
            items = []
            while self.peek() not in (")", None):
                if self.peek() == "(":
                    items.append(self.read_value())
                else:
                    tok2 = self.next()
                    items.append(_num(tok2) if not _is_str(tok2) else _unq(tok2))
            self.next()  # ')'
            return items
        if _is_str(tok):
            return _unq(tok)
        return _num(tok)

    def skip_props(self):
        while self.peek() == "PROP":
            self.next()
            if self.peek() == "(":
                self.skip_block()


def read_psf(path):
    """Return (sweep_name, sweep_values, traces) from a psfascii file.
    traces: dict name -> list of values (float or complex), one per point.
    For files without a sweep (op), sweep_name is None and each trace
    list has one value."""
    with open(path, "r", errors="replace") as fh:
        st = _Stream(_tokens(fh.read()))

    section = None
    sweep_name = None
    groups = {}
    points = []
    current = None

    while st.peek() is not None:
        tok = st.peek()
        if tok in _SECTIONS:
            section = st.next()
            if section == "END":
                break
            continue
        if tok == "(":
            st.skip_block()
            continue
        if tok == "PROP":
            st.skip_props()
            continue

        if section == "SWEEP":
            t = st.next()
            if _is_str(t) and sweep_name is None:
                sweep_name = _unq(t)
            continue

        if section == "TRACE":
            t = st.next()
            if not _is_str(t):
                continue
            name = _unq(t)
            if st.peek() == "GROUP":
                st.next()
                count = int(_num(st.next()) or 0)
                members = []
                for _ in range(count):
                    m = st.next()
                    st.next()              # member type
                    st.skip_props()
                    members.append(_unq(m) if _is_str(m) else m)
                groups[name] = members
            else:
                st.next()                  # trace type
                st.skip_props()
            continue

        if section == "VALUE":
            t = st.next()
            if not _is_str(t):
                continue
            name = _unq(t)
            if st.peek() is not None and _is_str(st.peek()):
                st.next()                  # type name (non-sweep files)
            val = st.read_value()
            st.skip_props()
            if sweep_name is not None and name == sweep_name:
                current = {name: val}
                points.append(current)
                continue
            if current is None:
                current = {}
                points.append(current)
            if name in groups and isinstance(val, list):
                for mname, mval in zip(groups[name], val):
                    current[mname] = _to_scalar(mval)
            else:
                current[name] = _to_scalar(val)
            continue

        st.next()  # HEADER / TYPE content: ignore

    names = []
    for p in points:
        for k in p:
            if k not in names:
                names.append(k)
    traces = {k: [p.get(k) for p in points] for k in names}
    sweep_vals = traces.pop(sweep_name, None) if sweep_name else None
    return sweep_name, sweep_vals, traces


def _to_scalar(v):
    if isinstance(v, float):
        return v
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, float) for x in v):
        return complex(v[0], v[1])
    return None   # struct or text: not used here


def find_file(rawdir, analysis):
    """results/<bench>.raw/<analysis>.<ext> (ext = dc, ac, noise, tran.tran ...)"""
    if not os.path.isdir(rawdir):
        return None
    hits = [f for f in os.listdir(rawdir) if f.startswith(analysis + ".")]
    if not hits:
        return None
    hits.sort(key=len)
    return os.path.join(rawdir, hits[0])


def load(bench, analysis):
    path = find_file(os.path.join(RES, bench + ".raw"), analysis)
    if path is None:
        return None
    try:
        return read_psf(path)
    except Exception as exc:
        say("  could not read %s (%s)" % (path, exc))
        return None


def trace(traces, *names):
    """get a trace by name, case-insensitive, first match wins"""
    low = {k.lower(): k for k in traces}
    for n in names:
        if n in traces:
            return traces[n]
        if n.lower() in low:
            return traces[low[n.lower()]]
    return None


# 2. small math helpers (no numpy needed)
def deriv(x, y):
    """central difference dy/dx, same length as x"""
    n = len(x)
    out = [0.0] * n
    for i in range(n):
        a, b = max(i - 1, 0), min(i + 1, n - 1)
        dx = x[b] - x[a]
        out[i] = (y[b] - y[a]) / dx if dx else 0.0
    return out


def interp(x, xs, ys):
    """linear interpolation, xs increasing; None if x is outside"""
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 <= x <= x1 and x1 != x0:
            return ys[i] + (ys[i + 1] - ys[i]) * (x - x0) / (x1 - x0)
    return None


def crossing(xs, ys, level):
    """first x where y crosses level (linear interpolation)"""
    for i in range(len(xs) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if (y0 - level) * (y1 - level) <= 0 and y1 != y0:
            return xs[i] + (level - y0) * (xs[i + 1] - xs[i]) / (y1 - y0)
    return None


def vth_sqrt(vgs, idd):
    """saturation Vth: tangent of sqrt(Id) at its max slope, x-intercept"""
    s = [math.sqrt(max(i, 0.0)) for i in idd]
    ds = deriv(vgs, s)
    k = max(range(len(ds)), key=lambda j: ds[j])
    return vgs[k] - s[k] / ds[k] if ds[k] > 0 else None


def vth_lin(vgs, idd, vds):
    """linear-region Vth: max-gm tangent of Id(Vgs), minus vds/2"""
    gm = deriv(vgs, idd)
    k = max(range(len(gm)), key=lambda j: gm[j])
    return vgs[k] - idd[k] / gm[k] - vds / 2.0 if gm[k] > 0 else None


def sub_slope(vgs, idd):
    """subthreshold swing in mV/decade (smallest value in weak inversion)"""
    best = None
    for i in range(1, len(vgs)):
        a, b = idd[i - 1], idd[i]
        if a > 1e-13 and b > a and b < 1e-7:
            ss = (vgs[i] - vgs[i - 1]) / (math.log10(b) - math.log10(a)) * 1e3
            best = ss if best is None else min(best, ss)
    return best


def write_csv(name, header, rows):
    path = os.path.join(RES, name)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["%.6g" % v if isinstance(v, float) else v for v in r])


def save_fig(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, name), dpi=150)
    plt.close(fig)


def mag(v):
    return abs(v) if v is not None else None


# 3. NMOS I-V
def nmos_iv():
    say("== NMOS I-V (W = 1 um, L = 60 nm) ==")
    fam = []
    for tag, v in [("04", 0.4), ("06", 0.6), ("08", 0.8), ("10", 1.0), ("12", 1.2)]:
        d = load("nmos_iv", "idvds_vgs" + tag)
        if d is None:
            continue
        vds = d[1]
        idd = [mag(x) for x in trace(d[2], "VD:p")]
        fam.append((v, vds, idd))
    if not fam:
        say("  no results (nmos_iv did not run)")
        return
    lin = load("nmos_iv", "idvgs_lin")
    sat = load("nmos_iv", "idvgs_sat")

    rows = []
    for v, vds, idd in fam:
        for x, y in zip(vds, idd):
            rows.append([v, x, y])
    write_csv("nmos_idvds.csv", ["vgs_V", "vds_V", "id_A"], rows)

    vt_lin = vt_sat = None
    if lin and sat:
        vg_l, id_l = lin[1], [mag(x) for x in trace(lin[2], "VD:p")]
        vg_s, id_s = sat[1], [mag(x) for x in trace(sat[2], "VD:p")]
        vt_lin = vth_lin(vg_l, id_l, 0.05)
        vt_sat = vth_sqrt(vg_s, id_s)
        ss = sub_slope(vg_s, id_s)
        say("  Vth (linear, vds=50 mV, max-gm method) = %.3f V" % vt_lin)
        say("  Vth (saturation, vds=1.2 V, sqrt(Id) method) = %.3f V" % vt_sat)
        say("  DIBL = %.0f mV/V" % ((vt_lin - vt_sat) / (1.2 - 0.05) * 1e3))
        found["nmos_vth"] = vt_sat
        found["dibl"] = (vt_lin - vt_sat) / (1.2 - 0.05) * 1e3
        found["ss"] = ss
        if ss:
            say("  subthreshold swing = %.0f mV/decade  (n = %.2f)"
                % (ss, ss / (1e3 * 0.02585 * math.log(10))))
        say("  Id at vgs = vds = 1.2 V: %.1f uA/um" % (fam[-1][2][-1] * 1e6))
        write_csv("nmos_idvgs.csv", ["vgs_V", "id_lin_A(vds=0.05)", "id_sat_A(vds=1.2)"],
                  [[a, b, c] for a, b, c in zip(vg_l, id_l, id_s)])

    if HAVE_PLT:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        for v, vds, idd in fam:
            ax.plot(vds, [i * 1e6 for i in idd], label="Vgs = %.1f V" % v)
        ax.set(xlabel="Vds (V)", ylabel="Id (uA)",
               title="NMOS Id-Vds (W/L = 1u/60n)")
        ax.grid(alpha=0.3)
        ax.legend()
        save_fig(fig, "spectre_nmos_idvds.png")

        if lin and sat:
            fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
            axs[0].plot(vg_l, [i * 1e6 for i in id_l], label="Vds = 50 mV")
            axs[0].plot(vg_s, [i * 1e6 for i in id_s], label="Vds = 1.2 V")
            axs[0].set(xlabel="Vgs (V)", ylabel="Id (uA)", title="Id-Vgs (linear scale)")
            axs[1].semilogy(vg_l, [max(i, 1e-15) for i in id_l], label="Vds = 50 mV")
            axs[1].semilogy(vg_s, [max(i, 1e-15) for i in id_s], label="Vds = 1.2 V")
            axs[1].set(xlabel="Vgs (V)", ylabel="Id (A)",
                       title="Id-Vgs (log scale): subthreshold slope and DIBL")
            for a in axs:
                a.grid(alpha=0.3, which="both")
                a.legend()
            save_fig(fig, "spectre_nmos_idvgs.png")


# 4. NMOS gm/Id data
def gm_id_tables():
    """returns dict L -> list of rows (dicts) with all small-signal data"""
    data = {}
    for L in LENGTHS:
        d = load("gm_id_sweep", "dc_L" + L)
        a = load("gm_id_sweep", "ac_L" + L)
        if d is None or a is None:
            continue
        vgs_dc, id_dc = d[1], [mag(x) for x in trace(d[2], "VDA:p")]
        vgs_ac = a[1]
        i_d = trace(a[2], "VDA:p")
        i_g = trace(a[2], "VGA:p")
        i_b = trace(a[2], "VDB:p")
        vth = vth_sqrt(vgs_dc, id_dc)
        ac_by_v = {}
        for v, x, g, b in zip(vgs_ac, i_d, i_g, i_b):
            ac_by_v[round(v, 6)] = (x, g, b)
        rows = []
        for v, idd in zip(vgs_dc, id_dc):
            key = round(v, 6)
            if key not in ac_by_v or idd is None or idd < 1e-9:
                continue
            x, g, b = ac_by_v[key]
            gm = abs(complex(x).real)
            cgg = abs(complex(g).imag) / (2 * math.pi * AC_FREQ)
            gds = abs(complex(b).real)
            if gm <= 0 or gds <= 0 or cgg <= 0:
                continue
            rows.append({
                "vgs": v, "vov": v - vth if vth is not None else float("nan"),
                "id": idd, "gm": gm, "gds": gds, "cgg": cgg,
                "gm_id": gm / idd, "id_w": idd / (WN * 1e6),     # A per um
                "gain": gm / gds, "ft": gm / (2 * math.pi * cgg),
            })
        for r in rows:
            r["fom"] = r["ft"] * r["gm_id"]
        data[L] = (vth, rows)
        write_csv("nmos_gmid_L%sn.csv" % L,
                  ["vgs_V", "vov_V", "id_A", "gm_S", "gds_S", "cgg_F", "gm_id_1/V",
                   "id_w_A/um", "gm_gds", "ft_Hz", "ft_x_gmid_Hz/V"],
                  [[r["vgs"], r["vov"], r["id"], r["gm"], r["gds"], r["cgg"], r["gm_id"],
                    r["id_w"], r["gain"], r["ft"], r["fom"]] for r in rows])
    return data


def strong_side(rows):
    """rows from the gm/Id peak towards strong inversion, sorted by gm/Id"""
    if not rows:
        return []
    k = max(range(len(rows)), key=lambda j: rows[j]["gm_id"])
    part = rows[k:]
    return sorted(part, key=lambda r: r["gm_id"])


def at_gmid(rows, key, target):
    part = strong_side(rows)
    return interp(target, [r["gm_id"] for r in part], [r[key] for r in part])


def gm_id_report(data):
    say()
    say("== NMOS gm/Id data (W = 1 um, vds = 0.6 V, f = 100 MHz for ac) ==")
    if not data:
        say("  no results (gm_id_sweep did not run)")
        return
    say("  L(nm)  Vth(V)  max gm/Id  max fT(GHz)  gm/gds@gm/Id=15  fT@15(GHz)  peak FoM at gm/Id")
    for L, (vth, rows) in data.items():
        if not rows:
            continue
        mx = max(r["gm_id"] for r in rows)
        ft = max(r["ft"] for r in rows) / 1e9
        g15 = at_gmid(rows, "gain", 15.0)
        f15 = at_gmid(rows, "ft", 15.0)
        best = max(rows, key=lambda r: r["fom"])
        found["gmid_max_" + L] = mx
        found["ft_max_" + L] = ft
        found["gain15_" + L] = g15
        say("  %5d  %6.3f  %9.1f  %11.1f  %15s  %10s  %9.1f"
            % (int(L), vth or float("nan"), mx, ft,
               "%.1f" % g15 if g15 else "-", "%.1f" % (f15 / 1e9) if f15 else "-",
               best["gm_id"]))

    say()
    say("  Sizing example: need gm = 1 mS at gm/Id = 15 /V  ->  Id = 1m/15 = 66.7 uA")
    for L, (vth, rows) in data.items():
        idw = at_gmid(rows, "id_w", 15.0)
        if idw:
            w = 66.7e-6 / idw
            say("    L = %3d nm: Id/W = %.1f uA/um  ->  W = %.2f um" % (int(L), idw * 1e6, w))

    if not HAVE_PLT:
        return
    lab = lambda L: "L = %d nm" % int(L)

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for L, (vth, rows) in data.items():
        ax.plot([r["vov"] * 1e3 for r in rows], [r["gm_id"] for r in rows], label=lab(L))
    ax.set(xlabel="Vov = Vgs - Vth (mV)", ylabel="gm/Id (1/V)", title="1) gm/Id vs Vov")
    ax.grid(alpha=0.3)
    ax.legend()
    save_fig(fig, "gmid_1_gmid_vs_vov.png")

    plots = [
        ("gain", "gm/gds = gm*ro (V/V)", "2) Intrinsic gain vs gm/Id", "gmid_2_gain.png", False, 1),
        ("ft", "fT (GHz)", "3) fT vs gm/Id", "gmid_3_ft.png", False, 1e-9),
        ("fom", "fT * gm/Id (GHz/V)", "4) fT*gm/Id vs gm/Id", "gmid_4_fom.png", False, 1e-9),
        ("id", "Id (uA)", "5) Id vs gm/Id", "gmid_5_id.png", True, 1e6),
        ("id_w", "Id/W (uA/um)", "6) Id/W vs gm/Id (use this to size W)", "gmid_6_idw.png", True, 1e6),
    ]
    for key, ylab, title, fname, logy, scale in plots:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        for L, (vth, rows) in data.items():
            xs = [r["gm_id"] for r in rows]
            ys = [r[key] * scale for r in rows]
            (ax.semilogy if logy else ax.plot)(xs, ys, label=lab(L))
        ax.set(xlabel="gm/Id (1/V)", ylabel=ylab, title=title)
        ax.grid(alpha=0.3, which="both")
        ax.legend()
        save_fig(fig, fname)

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for L, (vth, rows) in data.items():
        ax.semilogx([r["id"] for r in rows], [r["gain"] for r in rows], label=lab(L))
    ax.set(xlabel="Id (A)", ylabel="gm/gds (V/V)", title="Intrinsic gain vs Id")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    save_fig(fig, "gmid_7_gain_vs_id.png")


# 5. PMOS
def pmos_report(nmos_data):
    say()
    say("== PMOS (W = 1 um, L = 60 nm, source and body at %.1f V) ==" % VSUP)
    fam = []
    for tag, v in [("04", 0.4), ("06", 0.6), ("08", 0.8), ("10", 1.0), ("12", 1.2)]:
        d = load("pmos_iv", "isdvsd_vsg" + tag)
        if d is not None:
            fam.append((v, d[1], [mag(x) for x in trace(d[2], "VD:p")]))
    if not fam:
        say("  no results (pmos_iv did not run)")
        return
    dvg = load("pmos_iv", "isdvsg")
    pac = load("pmos_iv", "ac_pmos")
    rows = []
    if dvg and pac:
        vsg, isd = dvg[1], [mag(x) for x in trace(dvg[2], "VD:p")]
        found["pmos_vth"] = vth_sqrt(vsg, isd)
        say("  |Vth| (sqrt(Isd) method, vsd = 0.6 V) = %.3f V" % found["pmos_vth"])
        ac_by_v = {round(v, 6): (x, g, b) for v, x, g, b in
                   zip(pac[1], trace(pac[2], "VDA:p"), trace(pac[2], "VGA:p"),
                       trace(pac[2], "VDB:p"))}
        for v, i in zip(vsg, isd):
            key = round(v, 6)
            if key in ac_by_v and i and i > 1e-9:
                x, g, b = ac_by_v[key]
                gm, gds = abs(complex(x).real), abs(complex(b).real)
                cgg = abs(complex(g).imag) / (2 * math.pi * AC_FREQ)
                if gm > 0 and gds > 0 and cgg > 0:
                    rows.append({"vsg": v, "id": i, "gm_id": gm / i, "id_w": i / (WP * 1e6),
                                 "gain": gm / gds, "ft": gm / (2 * math.pi * cgg)})
        write_csv("pmos_gmid_L060n.csv",
                  ["vsg_V", "isd_A", "gm_id_1/V", "id_w_A/um", "gm_gds", "ft_Hz"],
                  [[r["vsg"], r["id"], r["gm_id"], r["id_w"], r["gain"], r["ft"]] for r in rows])
        say("  |Id| at vsg = vsd = 1.2 V: %.1f uA/um" % (fam[-1][2][-1] * 1e6))
        if rows and "060" in nmos_data:
            n_rows = nmos_data["060"][1]
            n15, p15 = at_gmid(n_rows, "id_w", 15.0), at_gmid(rows, "id_w", 15.0)
            if n15 and p15:
                found["pn_ratio"] = n15 / p15
                say("  At gm/Id = 15: NMOS Id/W = %.1f, PMOS Id/W = %.1f uA/um"
                    "  -> PMOS needs %.1fx more width" % (n15 * 1e6, p15 * 1e6, n15 / p15))

    if HAVE_PLT:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        for v, vsd, isd in fam:
            ax.plot(vsd, [i * 1e6 for i in isd], label="Vsg = %.1f V" % v)
        ax.set(xlabel="Vsd (V)", ylabel="|Id| (uA)", title="PMOS Isd-Vsd (W/L = 1u/60n)")
        ax.grid(alpha=0.3)
        ax.legend()
        save_fig(fig, "spectre_pmos_isdvsd.png")
        if rows and "060" in nmos_data:
            n_rows = nmos_data["060"][1]
            fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
            axs[0].semilogy([r["gm_id"] for r in n_rows], [r["id_w"] * 1e6 for r in n_rows], label="NMOS")
            axs[0].semilogy([r["gm_id"] for r in rows], [r["id_w"] * 1e6 for r in rows], label="PMOS")
            axs[0].set(xlabel="gm/Id (1/V)", ylabel="Id/W (uA/um)", title="Id/W: NMOS vs PMOS, L = 60 nm")
            axs[1].plot([r["gm_id"] for r in n_rows], [r["ft"] / 1e9 for r in n_rows], label="NMOS")
            axs[1].plot([r["gm_id"] for r in rows], [r["ft"] / 1e9 for r in rows], label="PMOS")
            axs[1].set(xlabel="gm/Id (1/V)", ylabel="fT (GHz)", title="fT: NMOS vs PMOS, L = 60 nm")
            for a in axs:
                a.grid(alpha=0.3, which="both")
                a.legend()
            save_fig(fig, "spectre_nmos_vs_pmos.png")


# 6. Common-source amplifier
def cs_bias():
    """pass 1: find vbias with V(out) = VSUP/2, write spectre/cs_bias.scs"""
    d = load("cs_amplifier", "dc_sweep")
    if d is None:
        print("cs-bias: no dc_sweep result found")
        return 1
    vin, vout = d[1], trace(d[2], "out")
    vb = crossing(vin, vout, VSUP / 2)
    if vb is None:
        print("cs-bias: V(out) never reaches %.2f V, keeping the old bias" % (VSUP / 2))
        return 1
    with open(os.path.join(SPECTRE_DIR, "cs_bias.scs"), "w") as fh:
        fh.write("// cs_bias.scs : bias point for cs_amplifier.scs\n")
        fh.write("// Written by analyze_spectre.py: vbias gives V(out) = %.2f V\n" % (VSUP / 2))
        fh.write("simulator lang=spectre\n")
        fh.write("parameters vbias=%.4f\n" % vb)
    print("cs-bias: vbias = %.4f V gives V(out) = %.2f V (written to spectre/cs_bias.scs)"
          % (vb, VSUP / 2))
    return 0


def read_vbias():
    try:
        with open(os.path.join(SPECTRE_DIR, "cs_bias.scs")) as fh:
            m = re.search(r"vbias\s*=\s*([0-9.eE+-]+)", fh.read())
        return float(m.group(1)) if m else None
    except OSError:
        return None


def cs_report():
    say()
    say("== Common-source amplifier (W/L = 2u/180n, RL = 10k, CL = 100f) ==")
    dc = load("cs_amplifier", "dc_sweep")
    ac = load("cs_amplifier", "ac_resp")
    nz = load("cs_amplifier", "noise_resp")
    tr = load("cs_amplifier", "tran_resp")
    op = load("cs_amplifier", "op_point")
    if dc is None:
        say("  no results (cs_amplifier did not run)")
        return
    vb = read_vbias()
    found["cs_vbias"] = vb
    say("  bias: vbias = %s V" % ("%.4f" % vb if vb else "?"))
    if op:
        i_dd = trace(op[2], "VDD:p")
        vo = trace(op[2], "out")
        if i_dd and i_dd[0] is not None:
            say("  Id = %.1f uA, V(out) = %.3f V" % (abs(i_dd[0]) * 1e6, vo[0] if vo else float("nan")))
    vin, vout = dc[1], trace(dc[2], "out")
    slope = deriv(vin, vout)

    if ac:
        f, h = ac[1], [abs(x) for x in trace(ac[2], "out")]
        a0 = h[0]
        bw = crossing(f, h, a0 / math.sqrt(2))
        ugf = crossing(f, h, 1.0)
        found["cs_gain"] = a0
        say("  low-frequency gain = %.2f V/V = %.1f dB" % (a0, 20 * math.log10(a0)))
        say("  -3 dB bandwidth = %s, unity-gain frequency = %s"
            % ("%.1f MHz" % (bw / 1e6) if bw else "-", "%.2f GHz" % (ugf / 1e9) if ugf else "-"))
        say("  check: gm ~ Av/(RL||ro) >= Av/RL = %.2f mS" % (a0 / RL * 1e3))
    if nz:
        f_n = nz[1]
        out_n = trace(nz[2], "out")
        in_n = trace(nz[2], "in")
        if in_n:
            in_n = [abs(x) for x in in_n]
            floor = min(in_n)
            corner = None
            for fx, v in zip(f_n, in_n):
                if v <= math.sqrt(2) * floor:
                    corner = fx
                    break
            say("  input-referred noise: %.2f nV/rtHz at 1 kHz, floor %.2f nV/rtHz"
                % (interp(1e3, f_n, in_n) * 1e9, floor * 1e9))
            found["noise_floor"] = floor
            if corner:
                found["noise_corner"] = corner
                say("  1/f corner (flicker = thermal) ~ %.0f kHz" % (corner / 1e3))

    if not HAVE_PLT:
        return
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.plot(vin, vout, label="V(out)")
    ax2 = ax.twinx()
    ax2.plot(vin, [-s for s in slope], "C1--", label="gain = -dVout/dVin")
    if vb:
        ax.axvline(vb, color="gray", ls=":")
        ax.annotate("bias %.3f V" % vb, (vb, VSUP / 2), xytext=(5, 5), textcoords="offset points")
    ax.set(xlabel="Vin (V)", ylabel="Vout (V)", title="CS amplifier DC transfer curve")
    ax2.set_ylabel("small-signal gain (V/V)")
    ax.grid(alpha=0.3)
    save_fig(fig, "cs_1_transfer.png")
    if ac:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        ax.semilogx(f, [20 * math.log10(max(x, 1e-12)) for x in h])
        ax.set(xlabel="Frequency (Hz)", ylabel="|Vout/Vin| (dB)", title="CS amplifier ac gain")
        ax.grid(alpha=0.3, which="both")
        save_fig(fig, "cs_2_ac_gain.png")
    if nz and out_n:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        ax.loglog(f_n, [abs(x) * 1e9 for x in out_n], label="output noise")
        if in_n:
            ax.loglog(f_n, [x * 1e9 for x in in_n], label="input-referred noise")
        ax.set(xlabel="Frequency (Hz)", ylabel="noise (nV/sqrt(Hz))",
               title="CS amplifier noise (1/f region, then thermal floor)")
        ax.grid(alpha=0.3, which="both")
        ax.legend()
        save_fig(fig, "cs_3_noise.png")
    if tr:
        t = tr[1]
        fig, axs = plt.subplots(2, 1, figsize=(6.5, 5), sharex=True)
        axs[0].plot([x * 1e6 for x in t], trace(tr[2], "inp"))
        axs[0].set(ylabel="Vin (V)", title="CS amplifier transient (5 mV, 1 MHz)")
        axs[1].plot([x * 1e6 for x in t], trace(tr[2], "out"))
        axs[1].set(xlabel="time (us)", ylabel="Vout (V)")
        for a in axs:
            a.grid(alpha=0.3)
        save_fig(fig, "cs_4_tran.png")


# 7. Process corners (compact model sections tt / ss / ff)
def corners_report():
    say()
    say("== Process corners (W/L = 1u/60n, |Vds| = 1.2 V) ==")
    tags = []
    if os.path.isdir(RES):
        for f in sorted(os.listdir(RES)):
            m = re.match(r"corners_(.+)\.raw$", f)
            if m:
                tags.append(m.group(1))
    order = {"ss": 0, "tt": 1, "ff": 2}
    tags.sort(key=lambda t: order.get(t, 9))
    curves = []
    if not tags:
        say("  no results (corners did not run)")
        return
    say("  corner   NMOS Vth(V)  NMOS Ion(uA/um)   PMOS |Vth|(V)  PMOS Ion(uA/um)")
    for t in tags:
        n = load("corners_" + t, "nmos_idvgs")
        pm = load("corners_" + t, "pmos_isdvsg")
        if n is None or pm is None:
            continue
        vn, idn = n[1], [mag(x) for x in trace(n[2], "VDN:p")]
        vp, idp = pm[1], [mag(x) for x in trace(pm[2], "VSP:p")]
        vtn, vtp = vth_sqrt(vn, idn), vth_sqrt(vp, idp)
        found["corner_ion_" + t] = idn[-1]
        found["corner_ionp_" + t] = idp[-1]
        say("  %-6s   %10.3f  %15.1f   %13.3f  %15.1f"
            % (t, vtn, idn[-1] * 1e6, vtp, idp[-1] * 1e6))
        curves.append((t, vn, idn, vp, idp))
    if HAVE_PLT and curves:
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
        for t, vn, idn, vp, idp in curves:
            axs[0].semilogy(vn, [max(i, 1e-15) for i in idn], label="NMOS " + t)
            axs[0].semilogy(vp, [max(i, 1e-15) for i in idp], "--", label="PMOS " + t)
            axs[1].plot(vn, [i * 1e6 for i in idn], label="NMOS " + t)
            axs[1].plot(vp, [i * 1e6 for i in idp], "--", label="PMOS " + t)
        axs[0].set(xlabel="|Vgs| (V)", ylabel="|Id| (A)", title="Corners, log scale")
        axs[1].set(xlabel="|Vgs| (V)", ylabel="|Id| (uA)", title="Corners, linear scale")
        for a in axs:
            a.grid(alpha=0.3, which="both")
            a.legend(fontsize=8)
        save_fig(fig, "corners_idvgs.png")


# 8. Sanity checks: is every key number where it should be?
def run_checks():
    lines = []
    counts = {"PASS": 0, "CHECK": 0, "MISSING": 0}

    def rng(label, key, lo, hi, unit=""):
        v = found.get(key)
        if v is None:
            st, txt = "MISSING", "not produced"
        else:
            st = "PASS" if lo <= v <= hi else "CHECK"
            txt = "%.3g %s (expected %g to %g)" % (v, unit, lo, hi)
        counts[st] += 1
        lines.append("  [%-7s] %-40s %s" % (st, label, txt))

    def cond(label, keys, test, txt):
        if any(found.get(k) is None for k in keys):
            st = "MISSING"
        else:
            st = "PASS" if test(*[found[k] for k in keys]) else "CHECK"
        counts[st] += 1
        lines.append("  [%-7s] %-40s %s" % (st, label, txt))

    rng("NMOS threshold voltage", "nmos_vth", 0.15, 0.7, "V")
    rng("NMOS subthreshold swing", "ss", 60, 130, "mV/dec")
    rng("NMOS DIBL", "dibl", 0, 300, "mV/V")
    rng("NMOS max gm/Id, L=60n", "gmid_max_060", 15, 40, "1/V")
    rng("NMOS max fT, L=60n", "ft_max_060", 10, 1000, "GHz")
    cond("fT falls with longer L", ["ft_max_060", "ft_max_500"], lambda a, b: a > b,
         "fT(60n) > fT(500n)")
    cond("gain rises with longer L", ["gain15_060", "gain15_500"], lambda a, b: b > a,
         "gm/gds(500n) > gm/gds(60n) at gm/Id = 15")
    rng("PMOS threshold voltage |Vth|", "pmos_vth", 0.15, 0.8, "V")
    rng("PMOS / NMOS width ratio", "pn_ratio", 1.1, 6, "x")
    rng("CS amplifier bias", "cs_vbias", 0.2, 1.0, "V")
    rng("CS amplifier gain", "cs_gain", 1.5, 60, "V/V")
    cond("Noise: 1/f corner found", ["noise_corner"], lambda c: c > 0, "flicker meets thermal floor")
    cond("Corners: NMOS Id ff > tt > ss",
         ["corner_ion_ff", "corner_ion_tt", "corner_ion_ss"],
         lambda f, t, s_: f > t > s_, "on-current order")
    cond("Corners: PMOS Id ff > tt > ss",
         ["corner_ionp_ff", "corner_ionp_tt", "corner_ionp_ss"],
         lambda f, t, s_: f > t > s_, "on-current order")

    lines.append("")
    lines.append("CHECKS: %d PASS, %d CHECK, %d MISSING"
                 % (counts["PASS"], counts["CHECK"], counts["MISSING"]))
    say()
    say("== Sanity checks ==")
    for l in lines:
        say(l)
    with open(os.path.join(RES, "checks.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    if "--cs-bias" in sys.argv:
        return cs_bias()
    os.makedirs(RES, exist_ok=True)
    os.makedirs(PLOTS, exist_ok=True)
    if not HAVE_PLT:
        say("NOTE: matplotlib not found, writing tables and summary only.")
    data = {}

    def guarded(title, func, *args):
        try:
            return func(*args)
        except Exception as exc:
            say("  %s: could not finish (%s: %s)" % (title, type(exc).__name__, exc))
            return None

    guarded("NMOS I-V", nmos_iv)
    data = guarded("gm/Id tables", gm_id_tables) or {}
    guarded("gm/Id report", gm_id_report, data)
    guarded("PMOS", pmos_report, data)
    guarded("CS amplifier", cs_report)
    guarded("Corners", corners_report)
    guarded("Checks", run_checks)
    with open(os.path.join(RES, "summary.txt"), "w") as fh:
        fh.write("\n".join(summary_lines) + "\n")
    print("\nSummary written to results/summary.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
