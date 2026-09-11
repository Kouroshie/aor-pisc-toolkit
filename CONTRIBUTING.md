# Contributing

Issues and pull requests are welcome. The things this project most needs, in
rough order of value:

1. **Validation against a commercial simulator.** The vertical-equilibrium
   solver is checked against an analytical solution and against its own
   conservation laws, not against CMG-GEM, ECLIPSE or TOUGH2. If you have a
   licensed model of a real site, running it side by side and opening an issue
   with the comparison is the most useful thing you can do here.
2. **Threshold-pressure methods from other state programmes.** The toolkit
   implements the two EPA methods, a variable-density generalisation, and the
   Texas/TCEQ mud-column approach. Other primacy states use other conventions.
   Each one should arrive with its citation and a test.
3. **Importers for other simulators.** STOMP, PFLOTRAN, Petrel exports, CMG
   `.rwo`.
4. **Worked examples from public permit applications**, so the shipped
   examples stop being hypothetical.

## Ground rules for code

- **Every equation carries its citation** in the docstring: paper, section,
  or CFR paragraph. If it cannot be cited it does not belong in this
  repository.
- **Every physical result carries a test.** Conservation laws, limiting cases
  and published numbers are all fair game; a test that only checks the code
  runs is not a test.
- **Regulatory text is quoted, not paraphrased**, and is marked with where it
  came from. Where the toolkit goes beyond what a regulation says, it says so.
- **SI internally, permit units at the boundary.** Nothing downstream of
  `containment.units` should have to guess.
- **Warn rather than assume.** If a model choice can quietly produce a wrong
  AoR - a domain that is too small, a threshold method applied outside its
  regime, an absolute-pressure column read as buildup - the code should say
  so in the result, not in a comment.

## Development

```bash
git clone https://github.com/Kouroshie/containment
cd containment
pip install -e ".[full,dev]"
pytest
ruff check src tests
```

The suite runs in well under a minute. Please keep it that way; if a test
needs a big model, mark it `@pytest.mark.slow`.

## Scope

In scope: anything that bears on delineating an Area of Review, identifying
and staging corrective action, or building a Post-Injection Site Care
demonstration for a UIC Class VI project.

Out of scope, at least for now: geochemistry, geomechanics, induced-seismicity
screening, and full 3-D compositional simulation. The Class VI Rule does not
require them in the AoR model, they are large projects in their own right, and
there are good tools for each.

## Licence

By contributing you agree that your contribution is licensed under the
Apache License 2.0, the same as the rest of the project.
