# Methods

Every equation the toolkit uses, what it assumes, and where it comes from.
Section numbers in the form "EPA Section 3.4.1" refer to
**EPA 816-R-13-005 (May 2013)**, *Geologic Sequestration of Carbon Dioxide:
UIC Program Class VI Well Area of Review Evaluation and Corrective Action
Guidance*.

Internally everything is SI (m, Pa, K, kg, s, m^2 for permeability). Inputs
and outputs are converted at the boundary by `containment.units`.

---

## 1. What an AoR is

> The area of review is the region surrounding the geologic sequestration
> project where USDWs may be endangered by the injection activity. The area
> of review is delineated using computational modeling that accounts for the
> physical and chemical properties of all phases of the injected carbon
> dioxide stream and displaced fluids
> - 40 CFR 146.84(a)

Operationally (EPA Section 3.4, Box 3-2) that is four steps:

1. compute the **threshold pressure**;
2. map the **maximum-over-time** extent of the pressure front;
3. map the **maximum-over-time** extent of the separate-phase plume;
4. take the **geometric union**.

Step 4 is a union, not a maximum of areas. EPA is explicit that "the region
encompassed by the pressure front will not in all cases be larger in all
directions than the extent of the separate-phase plume ... separate-phase
fluids may migrate beyond the extent of the pressure front."

---

## 2. Fluid properties (`containment.fluids`)

### CO2 density and viscosity

Default back-end is **CoolProp**: Span & Wagner (1996) Helmholtz EOS for
density, Fenghour, Wakeham & Vesovic (1998) for viscosity. This is the
reference implementation and is used whenever CoolProp is importable.

The dependency-free fallback uses:

* **Density**: the Spycher, Pruess & Ennis-King (2003) modified
  Redlich-Kwong EOS,

  ```
  P = RT/(V - b) - a(T) / (T^0.5 V (V + b))
  a(T) = 7.54e7 - 4.13e4 T   [bar cm^6 K^0.5 mol^-2]
  b    = 27.8                [cm^3/mol]
  R    = 83.1447             [bar cm^3 mol^-1 K^-1]
  ```

  solved as a cubic, taking the liquid root below the saturation pressure and
  the vapour root above it. Saturation pressure comes from the Span & Wagner
  ancillary equation.

* **Viscosity**: Fenghour et al. (1998), zero-density term plus the excess
  term, critical enhancement neglected.

**Accuracy of the fallback**, measured against CoolProp over 80-300 bar and
35-100 C: density typically within 1-4 %, viscosity within 1-8 %. It fails
badly in one place - near the critical point (about 74 bar, 31 C), where a
cubic EOS cannot follow the real fluid. At 80 bar / 35 C the fallback
over-predicts density by roughly 40 %. `fluids.near_critical()` detects this
region and `fluids.evaluate()` attaches a loud warning. That region matters:
CO2 density feeds straight into plume volume, and shallow storage formations
sit in it.

### Brine

Batzle & Wang (1992) for density (eq. 27 and 27b) and viscosity (eq. 32).
Accurate to roughly 0.5 % on density and 10 % on viscosity over storage
conditions. Compressibility is a central difference of the density
correlation. Salinity is carried as NaCl mass fraction;
`salinity_to_mass_fraction` accepts ppm, wt%, molality or fraction.

### Dissolution

**Off by default.** Neglecting CO2 dissolution into brine over-predicts the
separate-phase plume, which is the conservative direction for an AoR. The VE
solver accepts a `dissolution_fraction_per_year` if you want to include a
simple first-order sink, but the toolkit does not compute mutual solubilities
and therefore **cannot answer 40 CFR 146.93(c)(1)(v)** (trapping rates by
phase) on its own. For that, use a compositional or reactive-transport model,
and see Spycher & Pruess (2005) or Duan & Sun (2003) for the solubility
model.

---

## 3. Threshold pressure (`containment.threshold`)

The pressure front is not the edge of detectable pressure. It is

> the minimum pressure within the injection zone necessary to cause fluid flow
> from the injection zone into the formation matrix of the USDW through a
> hypothetical conduit (i.e., artificial penetration) that is perforated in
> both intervals
> - EPA Section 3.4.1

Depths are positive downward from a stated datum; EPA's elevations are
recovered as `z = -depth`, so `z_u - z_i == depth_i - depth_u`.

### Method 1 - Thornhill / equal hydraulic head (EPA Eq-1, Eq-2)

```
P_i,f  = P_u + rho_i g (z_u - z_i)
dP_i,f = P_i,f - P_i
```

Applicable when the injection zone is **under-pressurised** relative to the
lowermost USDW. The most conservative closed form, because it treats the
conduit as an open borehole carrying injection-zone brine at its in-situ
density all the way up. Thornhill et al. (1982); the long-standing UIC
pressure-front definition for other well classes.

### Method 2 - uniform-density borehole column (EPA Eq-3, Eq-4)

```
xi   = (rho_i - rho_u) / (z_u - z_i)
dP_c = 0.5 g xi (z_u - z_i)^2 = 0.5 g (rho_i - rho_u) (z_u - z_i)
```

Derivation, for the record: with an initially linear density profile the mean
column density is `(rho_i + rho_u)/2`; once injection-zone fluid has been
lifted to the top it is `rho_i`. The extra head to overcome is
`g (z_u - z_i) [rho_i - (rho_i + rho_u)/2]`, which is Eq-3.

Applicable to the **hydrostatic** case. Nicot et al. (2008); Bandilla et al.
(2012). Birkholzer et al. (2011) note the uniform-density form is the
conservative one for USDW protection.

### Method 2b - variable-density lifted column (this toolkit)

Method 2 assumes the lifted brine keeps its bottom-hole density all the way
up. Real brine expands as it rises and cools as it approaches the surface.
This method drops the constant-density assumption and integrates the column
directly:

```
dP_c = P_u + integral_{z_i}^{z_u} rho(z) g dz - P_i
```

with `rho(z)` evaluated from Batzle & Wang along the wellbore pressure and
temperature path, solved by two Picard sweeps. It reduces **exactly** to
Eq-3 for a constant `rho_i` (asserted in the test suite). It is offered as a
transparent generalisation of Method 2; it is **not** a reimplementation of
the "equilibrium approach" of Nicot et al. (2008), whose closed form is not
reproduced here.

### Method 3 - static mud column plus gel strength (TCEQ / UIC Class I)

Texas Class I practice, adopted in several Texas Class VI applications, does
not treat the conduit as an open brine-filled hole. It assumes the plugged
well stands full of ~9 lb/gal mud that has developed a gel strength:

```
dP_c = (mud gradient x depth_i + gel strength + P_surface) - P_i
```

9.0 ppg is 0.4675 psi/ft. References: Johnston & Knape (1986); TCEQ Class I
permitting practice; Bump (2023).

This method is **very sensitive to the depth datum**. The mud column must be
measured from the wellhead, not from sea level or a subsea marker. A worked
example: 9.0 ppg over 6,000 ft plus 10 psi gel, against an initial pressure
of 2,481 psi, gives 337 psi. The same site quoted at a 5,900 ft column gives
290 psi. Always state the datum next to the number.

### Over-pressurised injection zones

If `dP_i,f < 0` the injection zone is already over-pressurised and would leak
through an open conduit before injection starts. EPA Section 3.4.1 offers
three routes. `overpressured_allowance()` implements the first (the
density-contrast offset, `dP_c(Method 2) - |dP_i,f|`) and **flags itself as
inapplicable** when that difference is not positive, because the remaining two
routes - numerical wellbore-leakage modelling and a USDW dilution
demonstration - are outside what a closed form can supply.

### Where the threshold is evaluated

`dP_c` is a function of depth, and the depth is a choice. The toolkit defaults
to the mid-point of the injection zone; `threshold.datum: top` evaluates it at
the top of the interval, and `threshold.datum_depth` takes an explicit depth.

The difference is the weight of the brine column between the two datums. On a
313 ft injection interval that is roughly 157 ft of brine, about 75 psi, which
on a 714 psi threshold is more than 10 %. Two further percent comes from the
brine-density correlation: Rowe & Chou (1970) and Batzle & Wang (1992) differ
by ~1.4 % in density at 180,000 ppm, and because `dP_c` is a small difference
between two large numbers (`P_u + rho g dz - P_i`), a 1.4 % density change
moves the answer by 4 %. State the datum and the correlation alongside the
number.

### Choosing

`compare_methods()` runs all of them; `recommended()` returns the smallest
`dP_c` among those applicable to the site's pressure regime, because the
smallest allowable increase gives the largest pressure front and the most
protective AoR. The report shows all of them side by side, because the spread
between methods is the largest discretionary lever in an AoR delineation.

---

## 4. Relative permeability (`containment.analytical.relperm`)

Brooks-Corey / Corey power law on the normalised gas saturation:

```
Sn   = (Sg - Sgr) / (1 - Swr - Sgr)
k_rg = k_rg0 Sn^n
k_rw = k_rw0 (1 - Sn)^m
```

and van Genuchten-Mualem for models built against TOUGH2/ECO2N curves.

Fractional flow neglects capillary and gravity terms:

```
f_g = (k_rg/mu_g) / (k_rg/mu_g + k_rw/mu_w)
```

The Buckley-Leverett shock is found by the Welge tangent construction from
the initial state, numerically. `endpoint_mobility_ratio` returns

```
Gamma = (k_rg(1-Swr)/mu_g) / (k_rw(0)/mu_w)
```

which for CO2 in brine is typically 3-20.

EPA is blunt that "model predictions are very sensitive to the shape of the
relative permeability-saturation functions used" (Section 2.2.2), so these
curves are first-class objects carried through every model and every
sensitivity run rather than buried as constants.

---

## 5. Analytical plume models (`containment.analytical.plume`)

All are injection-period, homogeneous, horizontal, constant-thickness,
single-well models. They bracket the answer; they do not replace a gridded
model.

### Volumetric (mass balance)

```
r = sqrt( V_co2 / (pi phi Sg_avg H) )
```

Not a flow model. It is the floor every other estimate must exceed.

### Nordbotten, Celia & Bachu (2005) sharp interface

With `chi = 2 pi phi_eff H r^2 / (Q t)` and `phi_eff = phi (1 - Swr)`:

| region | dimensionless CO2 column |
|---|---|
| `chi <= 2/Gamma` | `h_c/H = 1` |
| `2/Gamma < chi < 2 Gamma` | `h_c/H = (sqrt(2 Gamma / chi) - 1)/(Gamma - 1)` |
| `chi >= 2 Gamma` | `h_c/H = 0` |

The nose sits at `chi = 2 Gamma`, so

```
r_max = sqrt( Gamma Q t / (pi phi_eff H) ) = sqrt(Gamma) x r_volumetric
```

For a typical CO2/brine `Gamma` of 3-20, the sharp-interface nose runs 1.7 to
4.5 times further than a volume balance. That factor is the single biggest
reason a volumetric AoR estimate is not defensible.

The profile integrates to exactly the injected volume; `test_analytical.py`
asserts this to 2 parts in 100,000.

### Radial Buckley-Leverett

```
r(S_g, t) = sqrt( Q_res t / (pi phi H) x df_g/dS_g(S_g) )
```

with the leading edge at the Welge shock saturation. This is the plume model
used by EASiTool. `saturation_cutoff` reproduces the operator convention of
outlining the plume at a chosen CO2 saturation (0.01-0.05).

### Residual-trapping ceiling

```
A_max = V_co2 / (phi H Sgr),   r_max = sqrt(A_max / pi)
```

The footprint of a plume that has migrated until every tonne is residually
trapped through the **full** interval thickness. A mass-balance ceiling on the
fully-swept area, and a useful check on a long-horizon PISC prediction. It is
**not** a ceiling on an outline drawn at a low saturation cutoff, which
legitimately extends further.

### Gravity number

```
Gamma_g = 2 pi k drho g H^2 / (mu_co2 Q_res)
```

Much greater than 1 means buoyancy dominates and the plume will be strongly
tongued; below about 1 means a viscous-dominated, near-cylindrical plume. Use
it to judge whether a sharp-interface model is adequate.

---

## 6. Analytical pressure (`containment.analytical.pressure`)

### Line source

```
dP(r, t) = q_res mu_w / (4 pi k H) x E1( r^2 / (4 eta t) )
eta      = k / (phi mu_w c_t)
```

`q_res` is the CO2 injection rate converted to reservoir volume,
`mass_rate / rho_co2`. Superposition is exact in time (rate differences) and
in space (wells plus images).

### Two-phase apparent skin

The two-phase bank around the wellbore behaves as a skin. It is evaluated by
integrating the Buckley-Leverett saturation profile:

```
S_a(t) = integral_{rw}^{rf(t)} ( lambda_w0 / lambda_t(r) - 1 ) d ln r
lambda_t = k_rg/mu_g + k_rw/mu_w
lambda_w0 = k_rw0/mu_w
```

This is the composite-radial form of the apparent skin used by Mathias et al.
(2011) and by EASiTool. For CO2 it comes out **negative** (typically -4 to
-8): CO2 is an order of magnitude less viscous than brine, so the bank
improves injectivity. An optional dry-out annulus at `Sg = 1` can be added.

Because `S_a` acts only inside `r_f`, it moves bottomhole pressure and
injectivity but leaves the far-field pressure front essentially untouched.
That is why a pressure-front AoR is far less sensitive to relative
permeability than a plume AoR.

### Boundaries by images

A rectangle with per-side no-flow or constant-pressure conditions is imposed
with an image lattice. Reflecting about `lo` then about `hi` is a translation
by `2L` that multiplies the weight by `s_lo s_hi`, so the 1-D lattice is

```
p + 2mL        weight (s_lo s_hi)^|m|
2 lo - p + 2mL weight s_lo (s_lo s_hi)^|m|
```

with `s = +1` for no-flow and `-1` for constant pressure. The 2-D lattice is
the outer product.

Two details that matter:

* **Truncate by distance from the domain centre, not by reflection index.**
  Index truncation clips the two families at different places and leaves the
  lattice lopsided; the symptom is a pressure field that is not symmetric even
  for a well on the axis of symmetry. This is asserted in the test suite.
* Images beyond several diffusion lengths contribute nothing, so they are
  pruned on `sqrt(4 eta t)`. Without pruning a large closed domain becomes a
  thousand-term sum for no gain.

---

## 7. Vertical-equilibrium solver (`containment.numerical.ve_solver`)

### Why VE

Storage formations are thin relative to the plume. Buoyant segregation is
fast compared with lateral spreading, so the vertical saturation distribution
collapses to a sharp CO2-over-brine interface almost everywhere. Integrating
that vertically leaves a 2-D areal problem that runs in seconds while still
capturing what moves an AoR boundary: dip and structure, heterogeneity,
sealing faults, multi-well interference, residual trapping, and
post-injection buoyant migration.

That last item is the reason the solver exists. The closed forms stop at the
end of injection; 40 CFR 146.84(c)(1) requires the model to run "until the
plume movement ceases, until pressure differentials sufficient to cause the
movement of injected fluids or formation fluids into a USDW are no longer
present, or until the end of a fixed time period".

### Formulation

State per cell: `psi` (brine pressure extrapolated to the top of the injection
zone) and `V` (CO2 pore volume). Mobile column `h` and its historical maximum
`hmax` follow from

```
V = phi A [ (1 - Swr) h + Sgr (hmax - h) ]
```

so `hmax - h` is the residually trapped trail behind a retreating plume.
Phase potentials, with `E` the top-surface elevation and
`drho = rho_w - rho_c`:

```
Phi_w = psi + rho_w g E
Phi_c = psi + drho g h + rho_c g E
```

The `drho g h` term is the buoyancy that drives up-dip migration; the
`rho g E` term is the structural drive. Upscaled face mobilities:

```
Lambda_c = k k_rg0 h / mu_c
Lambda_w = k [ k_rw0 (H - hmax) + k_rw(Sgr) (hmax - h) ] / mu_w
```

Two-point flux approximation with harmonic-mean face permeability, per-face
transmissibility multipliers for faults, and upwinded mobile thickness.

Time stepping is IMPES: an implicit sparse solve for `psi` on the total
volume balance with rock and fluid compressibility, then an explicit,
CFL-limited, upwind update of `V`. Timesteps land exactly on every well rate
change. Cells that fill the whole interval spill the excess to the
lowest-potential open neighbour, and any volume that cannot be placed is
tracked and reported as a mass-balance error.

Reference: Nordbotten & Celia (2012), *Geological Storage of CO2: Modeling
Approaches for Large-Scale Simulation*, Wiley.

### Graded grids

A uniform grid cannot serve both masters. The plume needs cells small enough
to resolve a buoyant tongue; the pressure front needs a domain tens of miles
across. `Grid.telescoping()` keeps fine cells over the well field and grows
them geometrically outward. Face widths and centre-to-centre distances are
taken per face, so a graded grid is handled exactly; mass balance on a graded
grid is asserted in the test suite.

### Validation against the analytical solution

With `Sgr = 0` (matching the NCB sharp-interface assumption), a flat
homogeneous formation and a single well, the VE interface profile tracks the
Nordbotten-Celia solution closely through the body of the plume. The nose is
more diffuse, as expected from numerical dispersion, so a like-for-like
comparison uses a small column-thickness cutoff. At a 5 % cutoff the
equivalent radius is within roughly 10 % of the analytical nose and the
agreement improves with refinement. See `docs/validation.md`.

---

## 8. Delineation (`containment.delineate`)

Fields are contoured with `contourpy` (matplotlib's contouring backend);
nested rings are resolved by containment parity so a ring inside a ring
becomes a hole, not a second island. Polygons come out as shapely geometry
and go out as GeoJSON, KML or CSV vertex lists.

`envelope()` takes the cell-wise maximum over a `(nt, ny, nx)` stack. That one
line is the difference between an AoR built on a snapshot and one built on
"the maximum extent ... over the lifetime of the project and entire timeframe
of the model simulations".

`AoRResult` reports the two components separately, says which one controls the
boundary and by how much, and gives extent by azimuth from a chosen point,
which is far more informative in a permit than a single area.

`compare_aors()` differences two delineations for an AoR reevaluation under
40 CFR 146.84(e). The `newly_included` geometry is exactly the area that
"must be subjected to the artificial penetration identification, assessment,
and corrective action procedures".

---

## 9. Corrective action (`containment.corrective`)

The EPA well-evaluation decision tree (Figure 4-3) is applied from record
completeness, plugging depth, plug material, abandonment date and MIT
results. Outcomes are `no action`, `field testing`, `corrective action` or
`monitor`, each with its reasoning and citation attached.

Two rules worth stating:

* **Unknown is not clean.** Missing or incomplete records route a well to
  field testing, per EPA Section 4.3.1, not to "no action".
* **Pre-1952 abandonment is suspect.** API published cement standards for oil
  and gas wells in 1952; EPA notes wells abandoned before then "may have
  inadequate plugs" (Section 4.2, citing Ide et al. 2006).

**Phased corrective action** is scheduled by *modelled arrival time* - the
year the plume or the pressure front first reaches each well - rather than by
distance. 40 CFR 146.84(b)(2)(iv) permits phasing at the Director's
discretion but nothing says how to phase it; arrival time is the defensible
criterion, and it falls out of the same model that produced the AoR. EPA
still expects all identified deficient wells to receive corrective action
before the end of the injection phase.

---

## 10. PISC (`containment.pisc`)

Four quantitative arguments, all computed from the same model output that
produced the AoR:

1. **plume area versus time** and its instantaneous expansion rate;
2. **effective-radius migration rate**,
   `r_eff = sqrt(A/pi)`, `rate = d r_eff / dt`;
3. **directional migration** along compass rays from each injector;
4. **pressure decline**: the year no cell anywhere exceeds the AoR threshold
   (146.93(c)(1)(ii)), and the year the maximum buildup falls within 5 % of
   its peak.

**Stabilisation** requires three tests to hold and keep holding to the end of
the simulation: migration rate below 5 % of its peak, below 50 ft/yr in
absolute terms, and footprint growth below 0.1 % of its own area per year.
The third test matters: 0.5 %/yr sounds small but compounds to +170 % over
200 years, and a plume creeping up-dip over a sparsely sampled tail will
otherwise be declared stable on the strength of a small ft/yr number.

The recommended PISC duration is the later of the plume and pressure
criteria. If either is never met inside the simulated horizon, the
recommendation says so loudly and refuses to rest on the other alone.

The 40 CFR 146.93(c)(1) and (c)(2) checklist is populated with the computed
values where the model can answer, and flagged as requiring project evidence
where it cannot - trapping narratives, laboratory and field studies,
confining-zone characterisation, an approved QASP. A modelling tool cannot
satisfy 146.93(c) by itself, and a checklist that pretends otherwise is worse
than none. The regulatory text quoted is transcribed from a Class VI permit
application's own crosswalk table; verify against the current CFR before
submitting.

---

## 11. Uncertainty (`containment.uncertainty`)

`tornado()` is one-parameter-at-a-time. `monte_carlo()` is Latin-hypercube
sampling over joint distributions (triangular, uniform, truncated normal,
truncated log-normal - all truncated to the stated range, because reservoir
properties do not have tails that reach negative values).

With gridded runs the ensemble accumulates a cell-wise inclusion probability,
from which a **probabilistic AoR** is contoured: P90 is the area nearly every
credible model includes; P10 is the outer envelope of what any of them does.
Rank (Spearman) correlations rank the inputs, because AoR area is a strongly
non-linear function of permeability and thickness and Pearson correlation
would mislead.

A counter-intuitive but correct result usually falls out: **higher
permeability shrinks the pressure-front AoR.** The buildup coefficient scales
as `1/k` while the diffusivity scales as `k`; solving
`(A/k) E1(u) = dP_c` gives `u ~ exp(-dP_c k / A)` and `r^2 ~ k u`, so beyond a
point the exponential wins. 40 CFR 146.93(c)(2)(vi) requires a sensitivity
analysis to support an alternative PISC timeframe; EPA Section 3.3.4 asks for
one to support the initial delineation.

---

## 12. Model-integrity checks

Results carry warnings rather than assuming the user will notice:

| check | why |
|---|---|
| AoR touching the domain edge, or filling > 40 % of it | EPA Section 3.3.3.2: the domain must extend beyond the plume and pressure front |
| pressure buildup on the model boundary as a fraction of the threshold | a no-flow edge that is too close inflates the front; a constant-pressure edge truncates it |
| fewer than ~20 cells across the plume | EPA Section 2.2.7 on coarse grids misrepresenting buoyancy-driven flow |
| CO2 mass-balance error in the VE solver | numerical integrity |
| threshold method applied outside its pressure regime | EPA Section 3.4.1 restricts Methods 1 and 2 explicitly |
| coarse post-injection output spacing | migration rates become long-interval averages |
| a fully closed domain used for PISC | pressure never dissipates, so the front never shrinks |
| penetrations in the AoR with no recorded total depth | 40 CFR 146.84(c)(2) requires depth for each |
| near-critical CO2 with the fallback EOS | tens of percent error in density, straight into plume volume |

---

## References

* Bandilla, K.W., Kraemer, S.R. & Birkholzer, J.T. (2012) *Int. J. Greenhouse Gas Control* **8**, 196-204.
* Batzle, M. & Wang, Z. (1992) *Geophysics* **57**, 1396-1408.
* Birkholzer, J.T. et al. (2011) *Int. J. Greenhouse Gas Control* **5**, 850-861.
* Fenghour, A., Wakeham, W.A. & Vesovic, V. (1998) *J. Phys. Chem. Ref. Data* **27**, 31-44.
* Ide, T., Friedmann, S.J. & Herzog, H. (2006) GHGT-8, Trondheim.
* Johnston, O.C. & Knape, B.K. (1986) *Pressure effects of the static mud column in abandoned wells*, Texas Water Commission.
* Mathias, S.A. et al. (2011) *Water Resour. Res.* **47**, W12525.
* Nicot, J.-P. et al. (2008); see also Bandilla et al. (2012) for the same solutions.
* Nordbotten, J.M., Celia, M.A. & Bachu, S. (2005) *Transp. Porous Media* **58**, 339-360.
* Nordbotten, J.M. & Celia, M.A. (2012) *Geological Storage of CO2*, Wiley.
* Span, R. & Wagner, W. (1996) *J. Phys. Chem. Ref. Data* **25**, 1509-1596.
* Spycher, N., Pruess, K. & Ennis-King, J. (2003) *Geochim. Cosmochim. Acta* **67**, 3015-3031.
* Thornhill, J.T. et al. (1982), as cited in EPA 816-R-13-005 Section 3.4.1.
* USEPA (2013) **816-R-13-005**, *UIC Program Class VI Well Area of Review Evaluation and Corrective Action Guidance*.


---

## Reading an AoR map where the boundary coincides with a component

The AoR is a geometric union, so whenever one component contains the other the
union **is** that component and the two boundaries are the same line. That is
not a corner case: EPA expects the separate-phase plume to run past the
pressure front at many sites, and a site whose pressure buildup never reaches
the threshold has no pressure front at all.

Drawn solid and on top, the AoR boundary paints over the component underneath,
and a reader cannot tell whether that component is missing, empty, or simply
hidden. Every map this toolkit draws -- the static figure, the interactive
figure and the web map -- therefore **dashes the AoR boundary whenever it
coincides with a component**, and says so in the legend. Where the AoR is a
genuine union that differs from both components, the boundary stays solid.

`AoRResult.coincident_with()` returns `"plume"`, `"pressure front"`, `"both"`
or `""`, so a report or a downstream figure can make the same distinction.
