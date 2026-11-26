"""
Looks for the PDK on the machine: cds.lib, the pdk library and the spectre
model file with its tt/ss/ff sections. Result goes to results/pdk_detect.env.

    python3 python/find_pdk.py
    python3 python/find_pdk.py --sections FILE
    python3 python/find_pdk.py --lib-only
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")

DEVICE_PAIRS = [("nch", "pch"), ("nch_mac", "pch_mac"), ("nmos1v", "pmos1v"),
                ("nfet", "pfet"), ("nmos", "pmos"), ("nmos4", "pmos4")]
SEARCH_DIRS = ["/cad", "/tools", "/opt", "/eda", "/apps", "/usr/local", "/pdk", "/pdks",
               "/home/cadence", "/share", "/projects"]
BUILTIN_LIBS = ("analogLib", "basic", "ahdlLib", "rfLib", "rfExamples", "functional", "sbaLib", "cdsDefTechLib", "US_8ths")
SECTION_RE = re.compile(r"^\s*section\s+([A-Za-z0-9_.\-]+)", re.I)
MAX_SECONDS = 150
MAX_DEPTH = 8
_t0 = time.time()


def log(msg):
    print("  [find_pdk] " + msg)


def parse_cdslib(path, seen=None, depth=0):
    """return list of (libName, libDir) defined in path (follows INCLUDE)"""
    seen = seen if seen is not None else set()
    out = []
    path = os.path.realpath(path)
    if path in seen or depth > 6 or not os.path.isfile(path):
        return out
    seen.add(path)
    base = os.path.dirname(path)
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.split("#")[0].split("--")[0].strip()
        parts = line.split()
        if len(parts) >= 2 and parts[0].upper() in ("INCLUDE", "SOFTINCLUDE"):
            inc = os.path.expanduser(os.path.expandvars(parts[1]))
            if not os.path.isabs(inc):
                inc = os.path.join(base, inc)
            out += parse_cdslib(inc, seen, depth + 1)
        elif len(parts) >= 3 and parts[0].upper() == "DEFINE":
            d = os.path.expanduser(os.path.expandvars(parts[2]))
            if not os.path.isabs(d):
                d = os.path.join(base, d)
            out.append((parts[1], os.path.normpath(d)))
    return out


def find_cdslibs():
    found = []
    starts = [os.getcwd(), os.path.expanduser("~")]
    for s in starts:
        for dirpath, dirnames, filenames in os.walk(s):
            if dirpath[len(s):].count(os.sep) >= 3:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "results"]
            if "cds.lib" in filenames:
                p = os.path.join(dirpath, "cds.lib")
                if p not in found and os.path.dirname(p) != os.path.join(ROOT, "virtuoso_work"):
                    found.append(p)
            if time.time() - _t0 > 30:
                break
    return found


def find_pdk_lib():
    """(cdslib, libName, libDir, ndev, pdev) of the best PDK library, or Nones"""
    for cds in find_cdslibs():
        for name, d in parse_cdslib(cds):
            if name in BUILTIN_LIBS:
                continue
            for n, p in DEVICE_PAIRS:
                if os.path.isdir(os.path.join(d, n)) and os.path.isdir(os.path.join(d, p)):
                    log("PDK library %s (%s) in %s" % (name, n, cds))
                    return cds, name, d, n, p
    return None, None, None, None, None


def sections_of(path):
    secs = []
    try:
        with open(path, errors="replace") as fh:
            for i, line in enumerate(fh):
                m = SECTION_RE.match(line)
                if m and m.group(1) not in secs:
                    secs.append(m.group(1))
                if i > 3000000:
                    break
    except OSError:
        pass
    return secs


def pick(secs, corner):
    """best section name for a corner (tt, ss, ff)"""
    low = [s.lower() for s in secs]
    for want in ("top_" + corner, corner, corner + "_lib", "tm" if corner == "tt" else "--",
                 "typical" if corner == "tt" else "--"):
        if want in low:
            return secs[low.index(want)]
    for s, l in zip(secs, low):
        if re.search(r"(^|_)%s($|_)" % corner, l) and "mc" not in l and "stat" not in l:
            return s
    return ""


def score(path, secs):
    sc = 0
    name = os.path.basename(path).lower()
    if name in ("toplevel.scs", "models.scs", "all.scs"):
        sc += 5
    if "spectre" in path.lower():
        sc += 2
    if "model" in path.lower():
        sc += 2
    if pick(secs, "tt"):
        sc += 4
    if pick(secs, "tt").lower() in ("tt", "top_tt"):
        sc += 6
    if pick(secs, "ss") and pick(secs, "ff"):
        sc += 2
    sc -= path.count(os.sep) * 0.1
    return sc


def walk_models(root, out):
    if not os.path.isdir(root):
        return
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if time.time() - _t0 > MAX_SECONDS:
            return
        if dirpath.count(os.sep) - base_depth >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if not f.lower().endswith(".scs"):
                continue
            p = os.path.join(dirpath, f)
            if p in out:
                continue
            try:
                if os.path.getsize(p) > 400e6:
                    continue
            except OSError:
                continue
            secs = sections_of(p)
            if secs and pick(secs, "tt"):
                out[p] = secs


def candidate_roots(pdk_dir):
    roots = []
    if pdk_dir:
        d = pdk_dir
        for _ in range(4):
            roots.append(d)
            d = os.path.dirname(d)
    for k, v in os.environ.items():
        if "PDK" in k.upper() and os.path.isdir(v):
            roots.append(v)
    return roots


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--sections":
        secs = sections_of(sys.argv[2])
        for c in ("tt", "ss", "ff"):
            print("%s=%s" % (c.upper(), pick(secs, c)))
        return 0

    os.makedirs(RES, exist_ok=True)
    cds, lib, libdir, ndev, pdev = find_pdk_lib()
    if "--lib-only" in sys.argv:
        with open(os.path.join(RES, "pdk_lib.env"), "w") as fh:
            fh.write("CDSLIB='%s'\nPDKLIB='%s'\n" % (cds or "", lib or ""))
        return 0
    models = {}
    for r in candidate_roots(libdir):
        log("searching %s" % r)
        walk_models(r, models)
        if len(models) >= 3:
            break
    if not models:
        for r in SEARCH_DIRS:
            log("searching %s" % r)
            walk_models(r, models)
    ranked = sorted(models, key=lambda p: -score(p, models[p]))[:6]
    log("found %d model file(s) with a tt section" % len(models))

    def q(s):
        return "'" + (s or "").replace("'", "'\\''") + "'"

    with open(os.path.join(RES, "pdk_detect.env"), "w") as fh:
        fh.write("CDSLIB=%s\nPDKLIB=%s\nPDKLIBDIR=%s\n" % (q(cds), q(lib), q(libdir)))
        fh.write("NDEV=%s\nPDEV=%s\n" % (q(ndev or "nch"), q(pdev or "pch")))
        fh.write("NMODELS=%d\n" % len(ranked))
        for i, p in enumerate(ranked, 1):
            secs = models[p]
            fh.write("MODEL_%d=%s\nTT_%d=%s\nSS_%d=%s\nFF_%d=%s\n"
                     % (i, q(p), i, q(pick(secs, "tt")), i, q(pick(secs, "ss")),
                        i, q(pick(secs, "ff"))))
            log("candidate %d: %s  (tt=%s ss=%s ff=%s)"
                % (i, p, pick(secs, "tt"), pick(secs, "ss"), pick(secs, "ff")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
