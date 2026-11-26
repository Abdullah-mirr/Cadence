# Virtuoso library

Library, schematics, symbols and the ADE runs.

| File | What it is |
|---|---|
| `study_lib.il` | SKILL script that builds the library `gmid_study` with all cells and views |
| `LIBRARY_GUIDE.md` | how to run it, what to check, how to do the same by hand |

## 1. What gets built

```
gmid_study                 <- library (a folder on disk, defined in cds.lib)
 |                            attached to the PDK technology
 |-- nmos_dut   schematic, symbol     <- nch + pins d g s b, W/L = 1u/60n
 |-- pmos_dut   schematic, symbol     <- pch + pins d g s b, W/L = 1u/60n
 |-- nmos_tb    schematic             <- test bench: nmos_dut + vdc VGS + vdc VDS + gnd
 `-- pmos_tb    schematic             <- test bench: pmos_dut + VSUP, VSG, VSD (see below)
```

- Library -> cell -> view. A library is a folder. Each cell is a sub-folder. Each view
  (`schematic`, `symbol`) is one representation of that cell.
- cds.lib maps the library name to its folder: `DEFINE gmid_study /path/gmid_study`.
  Without this line Virtuoso does not see the library.
- Technology attach. The library is attached to the PDK, so layers and device rules come from
  the kit.
- Hierarchy. The test benches do not use `nch` directly. They use the `nmos_dut` symbol, which
  points to the `nmos_dut` schematic. This is how every larger block is built.
- PMOS bench. The sources are stacked on the PMOS source node:
  VSUP sets the source to 1.2 V, VSG sits between source and gate, VSD sits between source and drain.
  So V(gate) = VSUP - VSG and V(drain) = VSUP - VSD, and the swept values are the real VSG and VSD.

## 2. Run the script

`bash go.sh` (in the main folder) already does this in the background, in the folder
`virtuoso_work/`. To see the library afterwards: `cd virtuoso_work && virtuoso &`, then
Tools -> Library Manager. The steps below are the same thing done in the Virtuoso window.


1. Start Virtuoso from your usual working folder (the one with `cds.lib`), for example:
   `cd ~/work && virtuoso &`
2. In the CIW (the main log window) type, with your real path:
   ```
   load("/home/<user>/cadence-study/virtuoso/study_lib.il")
   studyLibSetup()
   ```
3. Every step prints `OK` or `FAILED`. The last line shows the totals.
4. Open Tools -> Library Manager. The library `gmid_study` is in the list with the four cells.

If the first step fails (PDK library not found), type the PDK library name and run again:
```
studyPdkLib = "tsmcN65"
studyLibSetup()
```
(use the library name that holds `nch`, as shown in the Library Manager).

The script also writes `gmid_study_report.txt` in the Virtuoso start folder: library path,
technology, and every cell with its views.

Running it a second time is fine (close the gmid_study windows first). It reuses the library and redraws the cells. The symbol step may
say FAILED on a second run because the symbol already exists; that is not a problem.

## 3. Check the result by hand

1. Open `gmid_study / nmos_dut / schematic`. Select the transistor, press `q`: W = 1u, L = 60n.
   If a value looks different, type it again and press Tab so the PDK form updates.
2. Open `nmos_dut / symbol`: one pin per terminal.
3. Open `nmos_tb / schematic`. Select the `X0` instance and use Edit -> Hierarchy -> Descend Read
   to see the `nmos_dut` schematic inside. Edit -> Hierarchy -> Return goes back up.
4. Press `Shift+X` (Check and Save) in each schematic. There must be 0 errors.

## 4. Simulate the test bench in ADE

NMOS (`nmos_tb`)

1. In `nmos_tb` schematic: Launch -> ADE L (or ADE Explorer).
2. Setup -> Model Libraries: add the same model file and section as in `spectre/pdk_setup.scs`.
3. Variables -> Copy From Cellview. Set `VGS = 0.6`, `VDS = 0.6`.
4. Analyses -> Choose -> dc: Sweep Variable -> Design Variable -> `VGS`, 0 to 1.2, step 5m.
   Tick Save DC Operating Point.
5. Outputs -> To Be Plotted -> Select On Schematic: click the drain pin of `X0` (a circle shows
   the terminal current is selected). Press Esc.
6. Simulation -> Netlist and Run. The Id-Vgs curve appears.
7. Family of curves: Tools -> Parametric Analysis, variable `VGS` with values 0.4 0.6 0.8 1.0 1.2,
   and change the dc sweep to `VDS`, 0 to 1.2.
8. Simulation -> Netlist -> Display: compare the netlist with `spectre/nmos_iv.scs`.
   They describe the same circuit.

PMOS (`pmos_tb`)

Same steps, with variables `VSUP = 1.2`, `VSG = 0.6`, `VSD = 0.6`. Sweep `VSD` from 0 to 1.2 and use a
parametric sweep of `VSG`. The curves are positive and look like the NMOS curves, just smaller
(lower hole mobility).

Corners: Setup -> Model Libraries, add the same file once more with section `ss` and once with
`ff` (the names are in `results/pdk_detect.env`), then Tools -> Corners. Run and overlay:
Id(ff) > Id(tt) > Id(ss).

## 5. Screenshots

1. CIW with the `studyLibSetup()` output (all OK).
2. Library Manager showing `gmid_study` with its cells and views.
3. `nmos_dut` schematic and symbol.
4. `nmos_tb` schematic, and the descend into `X0`.
5. `pmos_tb` schematic with the stacked sources.
6. ADE window with model library, variables and analyses.
7. Id-Vgs and Id-Vds plots from ADE, NMOS and PMOS.
8. Corner plot (tt / ss / ff).

## 6. The same work by hand (no script)

This is what the script does, step by step in the GUI:

1. New library: Library Manager -> File -> New -> Library. Name `gmid_study`.
   Choose *Attach to an existing technology library* and pick the PDK library.
2. New cell: File -> New -> Cell View. Library `gmid_study`, cell `nmos_dut`, type `schematic`.
3. Place the transistor: press `i`, library = PDK, cell = `nch`, view = `symbol`. Set W and L.
4. Pins: press `p`, names `d g s b`, direction inputOutput. Wire them with `w`. `Shift+X`.
5. Symbol: Create -> Cellview -> From Cellview, from `schematic` to `symbol`. Accept the pin
   placement. Save.
6. Test bench: new cell `nmos_tb`, type `schematic`. Press `i`: `gmid_study/nmos_dut/symbol`,
   `analogLib/vdc` twice (DC voltage `VGS` and `VDS`), `analogLib/gnd`. Wire, `Shift+X`.
7. Copy, rename, delete (normal library work): in the Library Manager, right-click a cell ->
   Copy (e.g. `nmos_tb` to `nmos_tb_copy`), Rename, then Delete the copy.
