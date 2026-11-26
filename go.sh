#!/bin/bash
# runs the whole flow: find models, spectre runs, checks, virtuoso lib, collect results
# usage: bash go.sh   (cadence tools must be loaded first)

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
RES="$ROOT/results"
OUT="$ROOT/out"
WORK="$ROOT/virtuoso_work"
mkdir -p "$RES" "$ROOT/plots" "$OUT"
exec > >(tee "$OUT/go_log.txt") 2>&1

PASSED=0
FAILED_STAGES=""
NOTES=""

stage () {
    echo
    echo "=============================================================="
    echo "[STAGE $1/6] $2"
    echo "=============================================================="
}
pass () { echo ">>> [STAGE $1/6] PASS: $2"; PASSED=$((PASSED + 1)); }
fail () { echo ">>> [STAGE $1/6] FAIL: $2"; FAILED_STAGES="$FAILED_STAGES $1"; }
note () { NOTES="$NOTES\n  - $1"; }

final () {
    echo
    echo "##############################################################"
    if [ -z "$FAILED_STAGES" ]; then
        echo "##   ALL 6 STAGES PASSED"
    else
        echo "##   $PASSED of 6 stages passed.  FAILED STAGE(S):$FAILED_STAGES"
        echo "##   Look at the FAIL line of that stage above (also in out/go_log.txt)."
    fi
    [ -n "$NOTES" ] && echo -e "##   Notes:$NOTES"
    echo "##   Results collected in out/"
    echo "##############################################################"
}

# run one netlist from spectre/: spectre_run <netlist> <result name>
spectre_run () {
    ( cd "$ROOT/spectre" && \
      timeout 1800 spectre "$1.scs" -format psfascii -raw "$RES/$2.raw" > "$RES/$2.log" 2>&1 )
    grep -q "completes with 0 errors" "$RES/$2.log"
}

# write spectre/pdk_setup.scs: write_setup <model file> <section> <nmos> <pmos>
write_setup () {
    cat > "$ROOT/spectre/pdk_setup.scs" <<EOF
// model file + section, device names (set by go.sh)
simulator lang=spectre

include "$1" section=$2

subckt nmos_dut (d g s b)
parameters w=1u l=60n
    M0 (d g s b) $3 w=w l=l
ends nmos_dut

subckt pmos_dut (d g s b)
parameters w=1u l=60n
    M0 (d g s b) $4 w=w l=l
ends pmos_dut
EOF
}

stage 1 "Check the machine"
PY=""
for c in python3 python; do
    if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(sys.version_info[0] < 3)' 2>/dev/null; then
        PY=$c; break
    fi
done
command -v spectre  >/dev/null 2>&1 && echo "  spectre : $(command -v spectre)"  || echo "  spectre : NOT FOUND"
command -v virtuoso >/dev/null 2>&1 && echo "  virtuoso: $(command -v virtuoso)" || echo "  virtuoso: NOT FOUND"
[ -n "$PY" ] && echo "  python  : $(command -v $PY) ($($PY --version 2>&1))" || echo "  python  : NOT FOUND"
if [ -n "$PY" ] && ! $PY -c "import matplotlib" 2>/dev/null; then
    echo "  matplotlib: not installed (tables and checks still work, plots will be missing)"
    note "matplotlib missing: copy the folder to a PC with Python and run 'python python/analyze_spectre.py' for the plots"
fi

if ! command -v spectre >/dev/null 2>&1; then
    fail 1 "spectre not found. Load the Cadence tools first"
    final; exit 1
fi
if [ -z "$PY" ]; then
    fail 1 "python3 not found"
    final; exit 1
fi
pass 1 "spectre and python found"

stage 2 "Find the PDK models"
MODEL_FILE=""; TT_SEC=""
if ! grep -q "/EDIT/THIS/PATH" "$ROOT/spectre/pdk_setup.scs" && spectre_run check_setup check_setup; then
    echo "  existing spectre/pdk_setup.scs works, keeping it"
    MODEL_FILE=$(sed -n 's/^ *include *"\([^"]*\)" *section=.*/\1/p' "$ROOT/spectre/pdk_setup.scs" | head -1)
    TT_SEC=$(sed -n 's/^ *include .*section= *\([A-Za-z0-9_.-]*\).*/\1/p' "$ROOT/spectre/pdk_setup.scs" | head -1)
else
    echo "  searching this machine for the PDK (up to 3 minutes)..."
    $PY "$ROOT/python/find_pdk.py"
    NMODELS=0
    [ -f "$RES/pdk_detect.env" ] && . "$RES/pdk_detect.env"
    i=1
    while [ "$i" -le "${NMODELS:-0}" ] && [ -z "$MODEL_FILE" ]; do
        eval "m=\$MODEL_$i; tt=\$TT_$i"
        for pair in "$NDEV $PDEV" "nch pch"; do
            set -- $pair
            echo "  trying $m  section=$tt  devices=$1/$2"
            write_setup "$m" "$tt" "$1" "$2"
            if spectre_run check_setup check_setup; then
                MODEL_FILE="$m"; TT_SEC="$tt"; break
            fi
            [ "$pair" = "nch pch" ] && break
        done
        i=$((i + 1))
    done
    if [ -z "$MODEL_FILE" ] && [ -t 0 ]; then
        echo
        echo "  Could not find the models automatically."
        echo "  In Virtuoso ADE: Setup -> Model Libraries shows the file and section."
        read -r -p "  Model file path: " m < /dev/tty
        read -r -p "  Section name (e.g. top_tt or tt): " tt < /dev/tty
        write_setup "$m" "$tt" nch pch
        spectre_run check_setup check_setup && { MODEL_FILE="$m"; TT_SEC="$tt"; }
    fi
fi
if [ -n "$MODEL_FILE" ]; then
    echo "  model file : $MODEL_FILE"
    echo "  section    : $TT_SEC"
    pass 2 "models load (check_setup ran with 0 errors)"
else
    fail 2 "no working model file. Last Spectre messages:"
    tail -n 15 "$RES/check_setup.log" 2>/dev/null | sed 's/^/        /'
    echo "       Fix: put the model path and section in spectre/pdk_setup.scs, then run go.sh again."
    final; exit 1
fi

stage 3 "Run all Spectre simulations"
# 3a. process corners (compact model sections)
SS_SEC=""; FF_SEC=""
while IFS='=' read -r k v; do
    case "$k" in SS) SS_SEC="$v" ;; FF) FF_SEC="$v" ;; esac
done < <($PY "$ROOT/python/find_pdk.py" --sections "$MODEL_FILE")
rm -rf "$RES"/corners_*.raw
ncorner=0
for pair in "tt $TT_SEC" "ss $SS_SEC" "ff $FF_SEC"; do
    set -- $pair
    if [ -z "$2" ]; then
        echo "---- corner $1: no section found in the model file, skipped"
        note "corner $1 not found in the model file"
        continue
    fi
    sed "s/section=[A-Za-z0-9_.-]*/section=$2/" "$ROOT/spectre/pdk_setup.scs" > "$ROOT/spectre/pdk_corner.scs"
    echo "---- running corners.scs at $1 (section $2)"
    if spectre_run corners "corners_$1"; then
        echo "     OK"; ncorner=$((ncorner + 1))
    else
        echo "     FAILED (see results/corners_$1.log)"
        rm -rf "$RES/corners_$1.raw"
    fi
done
# 3b. all other benches + analysis
bash "$ROOT/run_all.sh"
RUN_ALL=$?
if [ $RUN_ALL -eq 0 ]; then
    pass 3 "all test benches ran with 0 errors ($ncorner corners)"
else
    fail 3 "a test bench failed (see the FAILED lines above and results/*.log)"
fi

stage 4 "Check the numbers"
if [ -f "$RES/checks.txt" ]; then
    cat "$RES/checks.txt"
    line=$(grep "^CHECKS:" "$RES/checks.txt")
    npass=$(echo "$line" | sed -n 's/CHECKS: \([0-9]*\) PASS.*/\1/p')
    ncheck=$(echo "$line" | sed -n 's/.* \([0-9]*\) CHECK.*/\1/p')
    if [ "${ncheck:-1}" -eq 0 ] && [ "${npass:-0}" -ge 10 ]; then
        pass 4 "$line"
    else
        fail 4 "$line  (a CHECK line means a value is outside its usual range: look at that plot)"
    fi
else
    fail 4 "results/checks.txt was not made (analysis did not run)"
fi

stage 5 "Build the Virtuoso library (in the background)"
if ! command -v virtuoso >/dev/null 2>&1; then
    fail 5 "virtuoso not found. Do it by hand: virtuoso/LIBRARY_GUIDE.md section 2"
else
    if [ -z "$CDSLIB" ]; then
        $PY "$ROOT/python/find_pdk.py" --lib-only
        [ -f "$RES/pdk_lib.env" ] && . "$RES/pdk_lib.env"
    fi
    mkdir -p "$WORK"
    {
        echo "-- cds.lib for the study library, written by go.sh"
        [ -n "$CDSLIB" ] && echo "SOFTINCLUDE $CDSLIB"
        [ -d "$WORK/gmid_study" ] && echo "DEFINE gmid_study $WORK/gmid_study"
    } > "$WORK/cds.lib"
    {
        echo "; .cdsinit for virtuoso_work: loads the normal lab start-up files"
        [ -n "$CDSLIB" ] && echo "when(isFile(\"$(dirname "$CDSLIB")/.cdsinit\") errset(load(\"$(dirname "$CDSLIB")/.cdsinit\") t))"
        [ "$(dirname "$CDSLIB")" != "$HOME" ] && echo "when(isFile(\"$HOME/.cdsinit\") errset(load(\"$HOME/.cdsinit\") t))"
    } > "$WORK/.cdsinit"
    rm -f "$WORK/build_status.txt"
    {
        echo "errset(load(\"$ROOT/virtuoso/study_lib.il\") t)"
        echo "studyLibDir = \"$WORK/gmid_study\""
        [ -n "$PDKLIB" ] && echo "studyPdkLib = \"$PDKLIB\""
        echo "errset(studyLibSetup() t)"
        echo "let((p) p = outfile(\"$WORK/build_status.txt\") when(p fprintf(p \"OK=%d FAILED=%d\\n\" studyOk studyFailed) close(p)))"
        echo "exit()"
    } > "$WORK/build_lib.il"
    echo "  running: virtuoso -nograph -restore build_lib.il (in virtuoso_work/)"
    ( cd "$WORK" && timeout 900 virtuoso -nograph -restore build_lib.il < /dev/null > "$WORK/virtuoso_build.log" 2>&1 )
    if [ ! -f "$WORK/build_status.txt" ]; then
        echo "  no result yet, trying again with: virtuoso -nograph -replay build_lib.il"
        ( cd "$WORK" && timeout 900 virtuoso -nograph -replay build_lib.il < /dev/null >> "$WORK/virtuoso_build.log" 2>&1 )
    fi
    grep -E "^  (OK|FAILED) |==== done" "$WORK/virtuoso_build.log" | sed 's/^/  /'
    if [ -f "$WORK/build_status.txt" ]; then
        st=$(cat "$WORK/build_status.txt")
        if echo "$st" | grep -q "FAILED=0"; then
            pass 5 "library gmid_study built ($st)"
        else
            fail 5 "some library steps failed ($st). Open Virtuoso and do those steps by hand (LIBRARY_GUIDE.md section 6)"
        fi
    else
        fail 5 "Virtuoso did not finish (license or start-up problem). See virtuoso_work/virtuoso_build.log,"
        echo "       or run it in the Virtuoso window instead: LIBRARY_GUIDE.md section 2"
    fi
fi

stage 6 "Collect the results"
for d in plots logs netlists library; do rm -rf "$OUT/$d"; mkdir -p "$OUT/$d"; done
cp "$RES"/summary.txt "$RES"/checks.txt "$OUT/" 2>/dev/null
cp "$RES"/*.env "$OUT/logs/" 2>/dev/null
cp "$RES"/*.log "$OUT/logs/" 2>/dev/null
cp "$RES"/*.csv "$OUT/" 2>/dev/null
cp "$ROOT"/plots/*.png "$OUT/plots/" 2>/dev/null
cp "$ROOT"/spectre/*.scs "$OUT/netlists/" 2>/dev/null
cp "$WORK"/gmid_study_report.txt "$WORK"/virtuoso_build.log "$WORK"/build_status.txt "$OUT/library/" 2>/dev/null
{
    echo "OUT FOLDER  (made by go.sh on $(date '+%Y-%m-%d %H:%M') on $(hostname))"
    echo
    echo "summary.txt            all key numbers (Vth, DIBL, swing, gm/Id table, PMOS, amplifier, corners)"
    echo "checks.txt             each number compared with its expected range"
    echo "*.csv                  gm/Id lookup tables per length"
    echo "plots/                 every figure"
    echo "netlists/              the Spectre test benches that were run (pdk_setup.scs shows the model file)"
    echo "logs/                  Spectre logs (each ends with 'completes with 0 errors')"
    echo "library/               Virtuoso library report and build log"
    echo "go_log.txt             everything go.sh printed"
    echo
    echo "Model file : $MODEL_FILE"
    echo "Section    : $TT_SEC"
    echo "Plots      : $(ls "$OUT/plots" 2>/dev/null | wc -l)"
} > "$OUT/INDEX.txt"
if [ -f "$OUT/summary.txt" ]; then
    pass 6 "out/ has $(ls "$OUT/plots" | wc -l) plots, summary, checks, logs, netlists"
else
    fail 6 "no summary.txt (the analysis did not run)"
fi

final
[ -z "$FAILED_STAGES" ] && exit 0 || exit 1
