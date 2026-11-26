# MOSFET Fundamentals

## 1. Structure and operation

An NMOS transistor has source, drain, gate, and body terminals. A gate voltage above the threshold voltage Vth
forms an inversion channel between source and drain. The overdrive voltage is Vov = Vgs - Vth.

## 2. Regions of operation (long-channel square-law model, NMOS)

| Region | Condition | Drain current |
|---|---|---|
| Cutoff / weak inversion | Vgs < Vth | ~0 (really exponential subthreshold current) |
| Triode (linear) | Vgs > Vth, Vds < Vov | Id = k'(W/L) [ Vov*Vds - Vds^2/2 ] |
| Saturation | Vgs > Vth, Vds >= Vov | Id = (k'/2)(W/L) Vov^2 (1 + lambda*Vds) |

where k' = un * Cox is the process transconductance parameter and lambda is the channel-length modulation coefficient.

## 3. Small-signal parameters

- Transconductance: gm = dId/dVgs = k'(W/L) Vov = 2 Id / Vov = sqrt(2 k' (W/L) Id)
- Output conductance: gds = dId/dVds ~ lambda * Id, so ro = 1/gds ~ 1/(lambda Id)
- Intrinsic gain: gm*ro ~ 2 / (lambda * Vov)
- Body transconductance: gmb = eta * gm (body effect, eta ~ 0.1 to 0.3)
- Capacitances: Cgs ~ (2/3) W L Cox in saturation, Cgd (overlap), Cdb and Csb (junction)
- Transit frequency: fT ~ gm / (2 pi (Cgs + Cgd))

## 4. Body effect

Vth = Vth0 + gamma * ( sqrt(|2 phi_F + Vsb|) - sqrt(|2 phi_F|) )

A raised source-to-body voltage increases Vth, which matters in stacked devices and source followers.

## 5. Second-order and short-channel effects

- Channel-length modulation: Id rises with Vds in saturation (finite ro).
- Velocity saturation: at high lateral field, Id becomes ~linear in Vov, not quadratic.
- Mobility degradation: vertical field reduces effective mobility.
- DIBL (drain-induced barrier lowering): Vth falls as Vds rises.
- Subthreshold conduction: Id ~ I0 exp(Vgs / (n * VT)) with VT = kT/q ~ 26 mV at room temperature.
- Short-channel Vth roll-off, gate leakage, and process variation (mismatch ~ 1/sqrt(W*L)).

## 6. The gm/Id design methodology

gm/Id (in 1/V) measures efficiency of turning current into transconductance:

- Weak inversion: gm/Id ~ 1/(n VT) ~ 25 to 30 1/V (maximum)
- Strong inversion (square-law): gm/Id = 2/Vov (falls as Vov rises)

Why does gm/Id fall in strong inversion? The main reason is the square law itself: gm/Id = 2/Vov,
so it falls as Vov rises. Velocity saturation and mobility degradation make it fall faster,
towards ~1/Vov in short devices, but they are not the first cause.

The upper limit 1/(n VT) cannot be passed: in weak inversion the current is exponential in Vgs, and
n > 1 because the gate controls the surface potential only through a capacitive divider (Cox and Cdep).

Designers pick gm/Id for each device, then size W/L from the current density Id/W. Lookup tables are built by sweeping the
real model in Spectre, which is why compact models matter.

## 7. Extracting parameters from simulations

| Parameter | How to extract |
|---|---|
| Vth | Id-Vgs in saturation, linear extrapolation or constant-current criterion |
| k' (or un*Cox) | Slope of sqrt(Id) vs Vgs, then k' = 2 * slope^2 / (W/L) |
| lambda | Slope of Id-Vds in saturation divided by Id |
| gm, gds | Spectre operating point (`oppoint`) or derivative of the sweeps |
| fT | ac sweep at a fixed frequency: gm = Re(i_d), Cgg = Im(i_g)/(2 pi f), fT = gm/(2 pi Cgg) |
| DIBL | Vth at Vds = 50 mV minus Vth at Vds = 1.2 V, divided by the Vds difference (mV/V) |
| Subthreshold swing | Smallest dVgs per decade of Id on a log plot, S = n * VT * ln(10) ~ 60 mV/dec * n |

## 8. PMOS sign convention

For a PMOS use positive quantities referred to the source: Vsg, Vsd, |Vth|. In a test bench the
source and body sit on VDD, and gate and drain are set as VDD - Vsg and VDD - Vsd. The equations are
the same as for the NMOS with un replaced by up, which is about 2 to 4 times smaller, so a PMOS needs
a wider device for the same current (see `results/summary.txt` for the ratio in our kit).

