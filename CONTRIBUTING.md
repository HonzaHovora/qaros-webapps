# Contributing

Adaptations here are for a broad audience: the ones the QAROS Visualizer shows in user mode.
The full guide, from fork to release: **Contribute an adaptation**,
https://docs.quaternar.com/docs/developer-guide/web-app-adaptations/contribute-an-adaptation

In short:

1. Fork this repository and check out the QAROS adaptation kit at `.qaros`
   (`git clone https://github.com/Quaternar/qaros .qaros`).
2. Add or change `adaptations/<name>/`. Shared code is a kit library named
   `"Library": "<name>@<major>"`, never a copy.
3. Bump that adaptation's `Version` and add one line to `CHANGELOG.md` under `[Unreleased]`, in the
   same commit ([AGENTS.md](AGENTS.md) has the rules).
4. Run what CI runs:

   ```
   python -I scripts/ci.py check --kit .qaros/adaptation-kit
   python -I scripts/build_packages.py --out out --kit .qaros/adaptation-kit
   ```

5. Test the package from `out/` in your Visualizer (Import app package), then open a pull request.

Releases (`YYYY.MM.DD.N`) and signing are done by CI on `main`; QAROS installs new versions by
itself. Writing an adaptation from scratch: the
[Web App Adaptations guide](https://docs.quaternar.com/docs/developer-guide/web-app-adaptations/).
