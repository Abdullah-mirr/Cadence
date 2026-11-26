#!/bin/bash
# runs the spectre benches and then the python post-processing
# usage: bash run_all.sh   (needs spectre/pdk_setup.scs filled in)

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
RES="$ROOT/results"
mkdir -p "$RES" "$ROOT/plots"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

ok_list=""
fail_list=""

# ---------- 1. basic checks ----------------------------------------
if ! command -v spectre >/dev/null 2>&1; then
    echo "ERROR: 'spectre' command not found."
    echo "Load the Cadence environment first (source the cshrc)."
    exit 1
fi

if grep -q "/EDIT/THIS/PATH" "$ROOT/spectre/pdk_setup.scs"; then
    echo "ERROR: spectre/pdk_setup.scs still has the placeholder model path."
    echo "Run  bash go.sh  instead: it finds the models by itself."
    exit 1
fi

# run_one <name> : runs spectre/<name>.scs, raw data in results/<name>.raw
run_one () {
    local name="$1"
    echo "---- running $name.scs"
    ( cd "$ROOT/spectre" && \
      spectre "$name.scs" -format psfascii -raw "$RES/$name.raw" > "$RES/$name.log" 2>&1 )
    if grep -q "completes with 0 errors" "$RES/$name.log"; then
        echo "     OK   (log: results/$name.log)"
        ok_list="$ok_list $name"
        return 0
    else
        echo "     FAILED, last lines of results/$name.log:"
        tail -n 25 "$RES/$name.log" | sed 's/^/        /'
        fail_list="$fail_list $name"
        return 1
    fi
}

# ---------- 2. smoke test: stop here if the models do not load -----
if ! run_one check_setup; then
    echo
    echo "The PDK setup does not work yet. Check the include path, the"
    echo "section name and the device names (nch/pch) in spectre/pdk_setup.scs."
    exit 1
fi

# ---------- 3. test benches ----------------------------------------
run_one nmos_iv
run_one pmos_iv
run_one gm_id_sweep

# common-source amplifier: pass 1 finds the bias, pass 2 uses it
if run_one cs_amplifier; then
    if $PY "$ROOT/python/analyze_spectre.py" --cs-bias; then
        cp -r "$RES/cs_amplifier.raw" "$RES/cs_amplifier_pass1.raw" 2>/dev/null
        run_one cs_amplifier
    fi
fi

# ---------- 4. plots and tables ------------------------------------
echo "---- making plots"
$PY "$ROOT/python/analyze_spectre.py" || echo "     plot script reported a problem (see above)"

echo
echo "Finished."
echo "  passed:${ok_list:- none}"
echo "  failed:${fail_list:- none}"
echo "Plots are in plots/, tables in results/, summary in results/summary.txt"
[ -z "$fail_list" ] && exit 0 || exit 1
