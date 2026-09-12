# Validation

What is tested, against what, and where it is checked. Run `pytest` to
reproduce all of it.

The tests are not smoke tests. Several of them found real bugs during
development, which are noted below, because a validation page that only lists
passes is not telling you much.

---

## 1. Threshold pressure against a published Class VI application

A published Class VI AoR and Corrective Action Plan states its Method 1
inputs and its answers in the same table. Feeding its inputs back in must
reproduce its numbers. The applicant, facility and well names are not
reproduced here; only the arithmetic is, because only the arithmetic is what
is being checked.

| well | inputs from the plan | plan's answer | toolkit |
|---|---|---|---|
| first injector | `P_u` 289 psi, `rho_i` 69.5 lb/ft3, `z_u` 1,217 ft, `z_i` 5,862 ft, `P_i` 1,817 psi | 714 psi | **713.4 psi** |
| second injector | `P_u` 289 psi, `rho_i` 66.8 lb/ft3, `z_u` 1,217 ft, `z_i` 8,076 ft, `P_i` 2,881 psi | 590 psi | **589.6 psi** |

Both agree to better than 1 psi, which is the rounding in the published table.

`tests/test_threshold.py::test_method1_reproduces_published_class_vi_value`
and `::test_method1_second_published_value`.

### Method 2b collapses to EPA Eq-3

The variable-density column integration must reduce exactly to EPA Eq-3 when
handed a constant column density, since Eq-3 is the constant-density case.
Checked to 1 part in a million.

`::test_variable_density_column_reduces_to_method2`.

### Method 3 arithmetic

9.0 ppg over 6,000 ft plus 10 psi gel, against 2,481 psi initial:
`0.4675 psi/ft x 6,000 + 10 - 2,481 = 337 psi`. Checked to 0.5 psi.

`::test_mud_column_arithmetic`.

### Regime gating

An under-pressurised site must mark Method 2 inapplicable; an over-pressurised
site with a 2,000 psi over-pressure must mark the density-contrast offset
inapplicable and point at EPA's numerical routes instead.

`::test_method2_flagged_not_applicable_when_underpressured`,
`::test_overpressured_path_flags_itself`.

---

## 2. Analytical plume: exact volume balance

The Nordbotten-Celia interface profile has to integrate to the injected
volume. Integrating `2 pi r phi_eff h_c(r)` over the plume and dividing by
`V_co2` gives **1.0000000** (checked to 2 parts in 100,000 on a 400,001-point
quadrature).

This is a strong check: it exercises the branch structure of the profile, the
`Gamma` dependence and the effective porosity together. Any algebra error in
the similarity solution breaks it.

`tests/test_analytical.py::test_nordbotten_celia_conserves_volume_exactly`.

Also checked: the nose is exactly `sqrt(Gamma)` times the volumetric radius;
plume radius scales as `sqrt(mass)`; the three plume models order themselves
volumetric < Buckley-Leverett < sharp-interface nose; and the
residual-trapping ceiling closes its own mass balance.

---

## 3. Analytical pressure: exact Theis, exact superposition

| check | result |
|---|---|
| single well vs. the closed-form exponential integral | agrees to 1e-10 relative |
| two wells vs. the sum of each alone | agrees to 1e-12 relative |
| a no-flow box gives higher buildup than an infinite aquifer | yes |
| a constant-pressure edge holds `dP` below 2 % of the centre value | yes |
| four points equidistant from an on-axis well give the same `dP` | agrees to 1e-6 relative |
| `radius_of_investigation` inverts the Theis solution | agrees to 1e-6 relative |

The equidistance test **found a real bug.** The image lattice was originally
truncated by reflection index, which clips the `+x0` and `-x0` families at
different places and leaves the lattice lopsided; the pressure field came out
0.16 % asymmetric for a well sitting exactly on the axis of symmetry.
Truncating by distance from the domain centre instead fixed it. A separate bug
in the constant-pressure case - a breadth-first reflection that assigned
weights by first-path-found - produced a "constant pressure" edge carrying
4.6 MPa. Both are now closed-form constructions with tests.

`tests/test_analytical.py`, the `test_*_boundary_*` and
`test_image_lattice_is_symmetric` cases.

### Two-phase apparent skin

For CO2 the composite-radial apparent skin comes out **negative** (CO2 is an
order of magnitude less viscous than brine, so the bank improves
injectivity), and its magnitude grows as the bank widens. Both are asserted.

---

## 4. Vertical-equilibrium solver

### Mass balance

CO2 mass balance closes to machine precision (`1e-16` relative) on both a
uniform grid and a graded telescoping grid.

`tests/test_numerical.py::test_ve_conserves_co2_mass`,
`::test_ve_conserves_mass_on_a_graded_grid`.

### Closed-system pressurisation

Injecting into a sealed box and letting it equilibrate must give

```
dP = injected volume / (pore volume x total compressibility)
```

The solver reproduces this to within 5 %, which is the residual of the
transient at the sampled time. This checks the accumulation term, the pore
volume, and the compressibility handling together.

`::test_closed_system_pressurisation_matches_volume_balance`.

### Convergence toward the analytical solution

Single well, flat, homogeneous, `Sgr = 0` (matching the sharp-interface
assumption), 5 MMT injected over 10 years. Nordbotten-Celia nose radius:
**3,822 ft** (`Gamma = 3.40`). Equivalent radius of the VE plume, contoured at
three column-thickness cutoffs:

| cell size | cells | `h/H >= 0.02` | `h/H >= 0.05` | `h/H >= 0.10` |
|---|---|---|---|---|
| 1,083 ft | 61 x 61 | 4,771 ft (+24.8 %) | 3,911 ft (+2.3 %) | 3,716 ft (-2.8 %) |
| 820 ft | 81 x 81 | 4,651 ft (+21.7 %) | 3,954 ft (+3.4 %) | 3,494 ft (-8.6 %) |
| 558 ft | 121 x 121 | 4,417 ft (+15.6 %) | 3,943 ft (+3.2 %) | 3,461 ft (-9.4 %) |
| 420 ft | 161 x 161 | 4,245 ft (+11.1 %) | 3,828 ft (+0.1 %) | 3,325 ft (-13.0 %) |

Read this honestly:

* At a **5 % column cutoff** the VE solver reproduces the sharp-interface nose
  to within 0.1-3.4 %, and the agreement improves with refinement.
* At a **2 % cutoff** the numerically diffuse nose adds 11-25 %, converging
  downward as the grid refines. This is numerical dispersion at the leading
  edge, and it is the reason a plume outline must state its cutoff.
* At a **10 % cutoff** the VE plume is 3-13 % *smaller*, because near the well
  the cell-averaged column under-represents the sharp analytical profile.

The practical lesson, which applies to any Class VI model and not just this
one: **the plume outline is a function of the cutoff at least as much as of
the physics**, and the sensitivity is worst exactly at the tapering nose where
the AoR boundary sits. State the cutoff, and test it.

`tests/test_numerical.py::test_ve_profile_converges_to_nordbotten_celia`.

### Physics that has to be there

| behaviour | test |
|---|---|
| a formation dipping south pushes CO2 north after shut-in | `test_dip_drives_the_plume_updip` |
| a fully sealing fault is not crossed | `test_sealing_fault_blocks_the_plume` |
| the swept footprint exceeds the mobile footprint once trapping is on | `test_residual_trapping_leaves_co2_behind` |
| a heterogeneous permeability field changes the footprint | `test_heterogeneity_changes_the_footprint` |
| pressure dissipates with open boundaries | `test_pressure_dissipates_with_open_boundaries` |
| column-averaged saturation stays within `[0, 1-Swr]` | `test_saturation_proxy_is_bounded` |

### Where the VE assumption stops being a good one

Vertical equilibrium collapses the injection zone into a single buoyant tongue
at its top. Whether that is a description or a caricature depends entirely on
the thickness of the zone and on what is inside it.

Rebuilding published Class VI applications and comparing against the
operator's own AoR figure shows the boundary clearly:

| gross zone thickness | how this toolkit compares against a 3-D compositional model |
|---|---|
| up to a few hundred feet | within a few per cent |
| ~500 ft and up, with internal shales | over-predicts, by 1.5x or more at ~2,000 ft |

The mechanism is straightforward. Given the same injected mass, a plume that
floats entirely to the top of a 2,000 ft package has less thickness to occupy
than one distributed across the individual sands near the completions, so it
spreads further. A 3-D model with `kv/kh` of 0.1 and shale baffles keeps much
of the CO2 down; this solver does not, because it cannot.

**What to do about it.** Up to a few hundred feet, use the VE result directly.
Past that, treat it as a conservative upper bound and say so in the plan -- it
errs in the protective direction, which is the right direction to err for an
AoR, but a reviewer should be told which way the model leans. Where the
individual sands are correlatable, run each as its own project on a pinned
frame and union the AoRs; that at least gets the per-sand thickness right.

A related warning sign: **on a thin zone the analytical and VE engines should
agree, and when they do not the zone thickness is usually the reason.** The
analytical radial Buckley-Leverett model distributes CO2 across the full
thickness; VE floats it. A large gap between the two engines at the same
inputs means the vertical distribution is doing more work than either model
can justify on its own. `workflow.run` reports both, and the cross-check is
there to be read, not skipped.

---

## 5. Delineation geometry

| check | result |
|---|---|
| contouring a radially symmetric disc recovers `pi R^2` | within 1 % |
| the AoR of two offset discs exceeds either alone and is less than their sum | yes |
| a plume entirely inside the pressure front is reported as such | yes |
| an empty pressure front is a warning, not a crash, and the AoR is the plume | yes |
| a contour running off the domain edge is flagged | yes |
| an AoR filling more than 40 % of the domain is flagged | yes |
| extent by azimuth recovers a circle's radius in all directions | within 3 % |
| differencing two AoRs recovers the added area | within 2 % |
| acres, square miles and square kilometres agree | exactly |

`tests/test_delineate_and_corrective.py`.

---

## 6. Corrective action decision tree

Every branch of EPA Figure 4-3 has a test: shallow well, good modern plug,
missing records, no plug across the confining zone, mechanical plug,
pre-1952 abandonment, failed MIT, active well. Plus point-in-polygon
screening, missing-depth warning, arrival-time ordering (a near well must be
reached before a far one), phase assignment, and identification of wells newly
inside a reevaluated AoR.

---

## 7. PISC

| check | result |
|---|---|
| effective radius recovers the radius that generated the areas | exactly |
| a plume that stops moving is declared stable | yes |
| a plume still creeping at 30 ft/yr is **not** declared stable, and the recommendation says so | yes |
| the pressure-below-threshold year is the first year the maximum buildup is under the threshold and stays under | yes |
| a pressure that never falls below the threshold returns `nan`, not a number | yes |
| a required PISC longer than the default is called out | yes |
| the 146.93(c) checklist has 18 rows and marks the trapping, laboratory-study and QASP items as **not** satisfiable by the model | yes |
| coarse post-injection output spacing is warned about | yes |
| directional migration finds a plume moving north and not south | yes |

The stabilisation test **changed during development** because of one of these
checks: a 0.5 %/yr area-growth tolerance let a plume creeping up-dip be
declared stable while the summary simultaneously warned it was still
expanding. The tolerance is now 0.1 %/yr, which still compounds to +22 % over
200 years.

---

## 8. Uncertainty

| check | result |
|---|---|
| the tornado ranks the parameter with the larger swing first | yes |
| Latin hypercube puts exactly one sample in each stratum of each dimension | yes |
| every distribution stays inside its stated range and stays positive | yes |
| the Monte Carlo inclusion probability spans 0 to 1 and P10 < P50 < P90 | yes |
| rank correlation identifies the driving parameter | yes |
| a probabilistic AoR contour has positive area | yes |

The positivity check **found a real bug**: an untruncated normal distribution
on permeability was returning negative values in the tails. All distributions
are now truncated to their stated range.

---

## 9. Fluids

| check | result |
|---|---|
| CO2 at 100 bar / 40 C is dense supercritical (560-700 kg/m3) | yes |
| CO2 density increases monotonically with pressure | yes |
| CO2 viscosity at 100 bar / 40 C is 0.049 cP (Fenghour reference point) | within 0.006 cP |
| CO2 saturation pressure at 20 C is 57.3 bar | within 1.5 bar |
| the built-in cubic EOS tracks CoolProp's Span-Wagner within 6 % | yes, away from the critical point |
| brine density rises with salinity and viscosity falls with temperature | yes |
| unit round-trips | exact to 1e-12 |
| 9.0 ppg is 0.4675 psi/ft | yes |

The CoolProp comparison test is skipped when CoolProp is not installed. Away
from the critical point the fallback holds 1-4 % on density and 1-8 % on
viscosity. **At 80 bar / 35 C it is 40 % wrong**, which is why
`fluids.near_critical()` exists and why CoolProp is a base dependency rather
than an extra.

---

## 10. Import and export

Long-format CSV import with layer aggregation (`max`, `sum`, `pv_weighted`,
`top`, `bottom`), the absolute-vs-buildup pressure convention and its
heuristic warning, ECLIPSE free-format keyword arrays with repeat syntax,
`.npz` round-trip, GeoJSON, KML and CSV vertex export, and both coordinate
transforms (exact via pyproj, approximate via a local tangent plane).

The pressure-convention heuristic **also changed because of a test**: the
original check looked for implausibly negative values, which catches the wrong
error. Reading absolute pressure as buildup produces implausibly *large
positive* values, and that is now what triggers the warning.

---

## 11. Against published applications

The most useful check available without a simulator licence is a published
Class VI application: the operator states an AoR area, prints a map of it, and
lists enough of the reservoir description to rebuild the case. Doing that for
several such applications is what produced the VE thickness guidance in
section 4 and both fixes in commit `1c8f0f2` (a foot-based projected CRS
silently scaling the model by 3.28; sealing faults being unreachable from a
project file).

Two things that exercise is good for, beyond the headline area:

* **A figure can be georeferenced from the well coordinates the applicant
  publishes**, by fitting a similarity transform to the wells visible on the
  map. On one application this recovered the figure's scale to 1.0 % of its own
  printed scale bar and its rotation to 0.2 degrees. That is enough to lay a
  modelled AoR over the operator's own map and compare them by shape, not just
  by area.
* **Sensitivity beats agreement.** Where an applicant omits a parameter, the
  useful output is not a number but a sweep: on one submission the AoR ran from
  331 sq mi to 0.7 sq mi as the net sand thickness went from 36 ft to 600 ft,
  which identifies precisely which missing number a reviewer has to request.

The runs themselves are not in this repository. Several of the source
documents are marked as containing confidential business information, so
nothing operator-specific is published here.

---

## What is not validated

* **No comparison against a commercial simulator.** The VE solver is checked
  against an analytical solution and against its own conservation laws, not
  against CMG-GEM, ECLIPSE or TOUGH2 directly -- only against the *published
  results* of such models, which is weaker because the inputs are never fully
  published. If you have a licensed model of a real site, running it against
  this toolkit and opening an issue with the comparison would be the single
  most valuable contribution to this project.
* **No field data.** Nothing here has been history-matched to a real
  injection.
* **Geochemistry, geomechanics and induced seismicity are out of scope**, so
  nothing about them is tested. The Class VI Rule does not require them in the
  AoR model, but the Director may.
* **Dissolution and mineral trapping rates** are not computed, so
  40 CFR 146.93(c)(1)(v) cannot be answered by this toolkit.
