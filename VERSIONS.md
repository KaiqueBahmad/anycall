# AnyCall Versions

This file tracks the version contract and implementation details across all languages.

## Version Contract

**Current Contract: 0.1**

The contract version (MAJOR.MINOR) is synchronized across all language implementations.
Implementations with the same contract version are guaranteed to be API-compatible and behaviorally equivalent.

---

## Current Releases

### Java
- **Contract**: 0.1
- **Implementation Version**: 0.1.0
- **Package**: `dev.kaiquebt:anycall`
- **Repository**: Maven Central
- **Status**: ✅ Published
- **Release Date**: 2026-06-14
- **Java Version**: 17+

### Python
- **Contract**: 0.1
- **Implementation Version**: 0.1.0
- **Package**: `anycall` (on PyPI)
- **Repository**: PyPI
- **Status**: ⏳ Pending
- **Release Date**: TBD
- **Python Version**: 3.8+

### Rust
- **Contract**: 0.1
- **Implementation Version**: TBD
- **Package**: `anycall` (on crates.io)
- **Repository**: crates.io
- **Status**: ❌ Not started
- **Release Date**: TBD
- **Rust Version**: 1.56+

---

## How to Update

### For a new contract version (e.g., 0.2):
1. Update `contract_version: "0.2"` below
2. Update all implementation versions to match X.Y (patches can differ)
3. Update `CHANGELOG.md` with the new section
4. Create git tag `v0.2`
5. Create language-specific tags: `java-v0.2.0`, `python-v0.2.0`, etc.

### For a language-specific patch (e.g., Java 0.1.1):
1. Update only the Java version: `0.1.1`
2. Update `CHANGELOG.md` Java section
3. Create git tag `java-v0.1.1` (does NOT change contract version)

---

## Git Tag Convention

```
# Release new contract version (all languages, new X.Y)
git tag v0.2
git push origin v0.2

# Release language-specific patch (only one language, new Z)
git tag java-v0.1.1
git push origin java-v0.1.1

git tag python-v0.1.1
git push origin python-v0.1.1
```

---

## CI/CD Workflows

### On `vX.Y` tag:
- Publishes all implementations with version X.Y.0
- Updates contract version in all repos

### On `{language}-vX.Y.Z` tag:
- Publishes only that language with version X.Y.Z
- Does NOT update contract version

---

## Compatibility Matrix

| Version | Java | Python | Rust | Status |
|---------|------|--------|------|--------|
| 0.1     | 0.1.0 | 0.1.0 (pending) | — | In Development |
| 0.2     | — | — | — | Planned |

When a user picks version 0.1, they get:
- Java: 0.1.0 (or later patch like 0.1.2)
- Python: 0.1.0 (or later patch like 0.1.1)
- All are API-compatible, can interoperate
