# Cadence Virtuoso: Environment, Libraries, Schematics, Spectre Simulation

## 1. The environment

- CIW (Command Interpreter Window): the main Virtuoso window. It shows logs and errors and accepts SKILL commands.
- Library Manager: where libraries, cells, and views are created and organised.
- Schematic Editor (Virtuoso Schematic Editor XL): used to draw circuits.
- ADE (Analog Design Environment: ADE L / XL / Assembler): used to set up and run simulations with Spectre, and to view results.
- Waveform Viewer: shows simulation outputs and supports a calculator for measurements.

Start-up is typically `virtuoso &` from a terminal in a directory containing `cds.lib` (library paths) and
optionally `.cdsinit` (start-up SKILL).

## 2. Library management

Data is organised as Library, Cell, View:

| Level | Meaning | Example |
|---|---|---|
| Library | A collection of cells | `my_analog_lib` |
| Cell | A design block | `cs_amp` |
| View | A representation of a cell | `schematic`, `symbol`, `layout`, `config` |

Key points:

- `cds.lib` maps library names to directories (`DEFINE my_analog_lib ./my_analog_lib`).
- The technology/PDK library provides the devices. Names depend on the kit: `gpdk045` uses `nmos1v` / `pmos1v`,
  TSMC 65 nm uses `nch` / `pch`. Our lab kit uses `nch` / `pch`.
- A new design library must be attached to a technology library when it is created, so that layout and
  device properties resolve correctly.
- `analogLib` provides ideal sources and passives (`vdc`, `vpulse`, `vsin`, `idc`, `gnd`, `vdd`).

## 3. Schematic design flow

1. Library Manager -> File -> New -> Cell View. Choose type *schematic* (older versions call the tool *Composer-Schematic*).
2. Add instances with `i`: transistors from the PDK, sources from `analogLib`.
3. Wire with `w`, add pins with `p`, set properties with `q`.
4. Check and save with `Shift+X` (Check and Save). Fix any warnings about floating nets or missing grounds.
5. Create a symbol if the block will be reused: Create -> Cell View -> From Cell View.

Best practices:

- Always include a `gnd` reference.
- Label nets (`l`) that you want to probe.
- Parametrise W, L, and bias values with variables so they can be swept in ADE.

## 4. Simulating with Spectre via ADE

1. In the schematic: Launch -> ADE L (or ADE Explorer/Assembler).
2. Setup -> Simulator -> `spectre`. Setup -> Model Libraries: point to the PDK model file and select the corner (tt, ss, ff).
3. Choose analyses (Analyses -> Choose):
   - dc: sweep a source or parameter (I-V curves, transfer characteristics)
   - ac: small-signal frequency response (gain, bandwidth, phase margin)
   - tran: transient response
   - noise, stb (stability), pss and others for advanced work
4. Outputs -> To Be Plotted -> Select on Schematic: click the nets or terminals to plot.
5. Simulation -> Netlist and Run. Results open in the Waveform Viewer.
6. Use the Calculator for gain (`dB20`), bandwidth (`bandwidth`), and so on.

Useful extras: Tools -> Parametric Analysis for sweeps, Corners for PVT, and Simulation -> Netlist -> Create
to inspect the generated Spectre netlist (this is a good way to learn Spectre syntax).

## 5. Spectre netlist basics

```
simulator lang=spectre
include "/path/to/pdk/models.scs" section=tt
parameters vgs=0.6
VD (d 0) vsource dc=1.2
VG (g 0) vsource dc=vgs
M0 (d g 0 0) nch w=1u l=100n
sweep_vgs dc param=vgs start=0 stop=1.2 step=10m
save M0:oppoint
```

- Instances: `name (nodes) master params`
- Analyses are statements (`dc`, `ac`, `tran`) with their own name
- Output formats: `psfascii`, `psf`, `nutascii`
- `alter` changes a parameter between analyses, for example
  `setL alter param=lval value=170n` followed by another `dc` analysis
- An `ac` analysis can sweep a parameter at one fixed frequency:
  `ac1 ac param=vgs start=0 stop=1.2 step=5m freq=100M`. This is how
  `gm_id_sweep.scs` gets gm, gds and Cgg at every bias point

## 6. Checks before trusting a plot

- Bias reference for PMOS. Put source and body on the supply and set the gate and drain
  relative to the source (`V(g) = VDD - VSG`). If the gate source is referred to ground while the
  source moves, the real VSG changes during the sweep and every PMOS curve is wrong.
- Units on every axis. Output resistance is in ohm (kOhm), not uOhm. If the unit looks strange,
  the calculator expression is usually wrong (for example plotting gds instead of 1/gds).
- Legend and title must agree. If the title says "VGS sweep", the legend must list VGS values.
- Cross-check numbers between plots. fT read from an ac marker must match fT from the
  `fT vs gm/Id` curve at the same bias. If not, one of the two set-ups is wrong.
- Sine sources in tran. `dc=` is used only by dc/ac/noise. The transient offset is `sinedc=`.
- Bias first, then ac/noise. Check in the dc operating point that the transistor is in
  saturation (Vds > Vdsat) before reading gain or noise.

## 7. Things to practise

- [x] Build an NMOS test bench and sweep Vgs for Id-Vgs
- [x] Sweep Vds at several Vgs for Id-Vds
- [x] Build a resistor-loaded common-source amplifier and run ac analysis
- [x] Extract gm, gds, and Cgg at every bias point (`spectre/gm_id_sweep.scs`)
- [x] Create my own library attached to the PDK, with symbols and test benches (`virtuoso/study_lib.il`)
- [ ] Take the screenshots listed in `virtuoso/LIBRARY_GUIDE.md`
- [x] Run the same devices at the tt, ss and ff corners (`spectre/corners.scs`)
