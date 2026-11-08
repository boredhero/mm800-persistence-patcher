# Release checklist

1. Review every staged file and confirm no firmware, backups, generated
   images, decompiler exports, or encoded firmware are present.
2. Run all source-only tests and confirm no CI artifact contains firmware.
3. Verify the exact supported stock application length and SHA-256.
4. Require a deterministic build and record the actual output hash.
5. Preserve two verified full backups outside the repository.
6. Test candidate installation and complete readback.
7. Verify stock fallback, live RGB, read-only EEPROM backup, exact profile
   save, power-cycle restoration, A/B fallback, and stock restoration.
8. Record the tested image hash, device identity, toolchain, and scope in
   `docs/hardware-test-results.md`.
9. Review all claims for unsupported safety, legality, recovery, or universal
   compatibility language.
10. Publish source only. Do not attach patched binaries or firmware artifacts
    to releases, issues, packages, CI, or the wiki.

If any required item is unresolved, keep the project marked experimental or
delay the release. Do not fill gaps with optimistic wording.
