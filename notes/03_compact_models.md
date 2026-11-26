# MOSFET Compact Models

A compact model is a set of analytical equations, with fitted parameters, that predicts transistor terminal
currents, charges, and capacitances fast enough to run inside a circuit simulator such as Spectre (as opposed to TCAD,
which solves device physics numerically and is far too slow for circuits).

## Evolution of models

| Model | Era | Notes |
|---|---|---|
| SPICE Level 1 (Shichman-Hodges) | 1960s-70s | Square-law, a few parameters (VTO, KP, GAMMA, PHI, LAMBDA). Good for teaching. |
| Level 2 / Level 3 | 1980s | Added short-channel and mobility effects, semi-empirical. |
| BSIM3v3 | 1990s | Industry standard for 0.35 um to 130 nm. Threshold-voltage based. |
| BSIM4 | 2000s | Adds gate tunnelling, stress effects, improved noise models. |
| BSIM-CMG / BSIM-IMG | 2010s | Multi-gate models for FinFET and FD-SOI. |
| PSP, EKV | | Surface-potential and charge-based models with continuous weak-to-strong inversion behaviour. |

## What a good compact model needs

- Continuity across all regions (smooth transitions, so Newton-Raphson iterations in the simulator converge)
- Charge conservation for transient simulation
- Accurate derivatives (gm, gds, capacitances) for small-signal and RF work
- Scalability across W, L, temperature, and process corners
- Noise models (thermal, flicker)

## Key BSIM-style parameters (conceptual)

- `VTH0`: long-channel threshold voltage at zero body bias
- `U0`: low-field mobility
- `TOXE`: electrical gate-oxide thickness (sets Cox)
- `VSAT`: saturation velocity
- `K1`, `K2`: body-effect coefficients
- `ETA0`, `DSUB`: DIBL parameters
- `PCLM`: channel-length modulation
- `NFACTOR`: subthreshold swing factor
- `CGSO`, `CGDO`: overlap capacitances

## Practical use in Virtuoso/Spectre

- The PDK supplies model files (`.scs` / `.lib`) with process corners (tt, ff, ss, fs, sf).
- Select the corner in ADE (Setup -> Model Libraries).
- Many PDKs wrap the BSIM device in a sub-circuit (for example `nch` contains an internal
  instance). Then `M0:gm` may not exist at the top level. Reading terminal currents from a
  dc and ac sweep (as in `spectre/gm_id_sweep.scs`) works for any kit.
- The `oppoint` output prints gm, gds, gmb, Vth, Vdsat, Cgs, and Cgd for each device. Comparing these with hand calculations from the
  square-law model is a good way to see where square-law fails in short-channel technologies.

## Square-law vs. real model

In modern nodes, hand calculations with the square-law model are only a starting point: velocity saturation makes Id ~ linear
in Vov, DIBL lowers ro, and gm/Id from the real model deviates from 2/Vov. Hence the workflow:
hand estimate -> simulate with the real model -> iterate.

## Corners in ADE

1. ADE -> Setup -> Model Libraries: the model file is listed once per section (tt, ss, ff ...).
2. Tools -> Corners (ADE L) or the Corners set-up in ADE Explorer/Assembler: add a corner per
   section, and optionally temperature (-40, 27, 125 C) and supply (+-10%).
3. Run and overlay the results. Expect Id(ff) > Id(tt) > Id(ss), and Vth moving the other way.

