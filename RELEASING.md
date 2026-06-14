# Release Guide - AnyCall Polyglot Versioning

This guide explains how to release AnyCall following the polyglot versioning model.

## Version Model

- **Contract Version (X.Y)**: Synchronized API across all languages
- **Patch Version (Z)**: Independent bug fixes per language

Example:
- Java: 0.1.0, 0.1.1, 0.1.2
- Python: 0.1.0, 0.1.1
- All are **contract 0.1**, fully compatible

## Release Types

### Type 1: Contract Release (New API Version)

Use when adding features or making changes that affect all implementations.

**Example**: Releasing contract 0.2 with new RPC features

```bash
# 1. Update pom.xml, setup.py, Cargo.toml to 0.2.0
# 2. Update CHANGELOG.md with [0.2] section
# 3. Update VERSIONS.md

git add java/pom.xml python/setup.py CHANGELOG.md VERSIONS.md
git commit -m "chore(release): bump contract to 0.2"

# 4. Tag and push
git tag v0.2
git push origin v0.2
```

**What happens:**
- GitHub Actions publishes Java 0.2.0 to Maven Central
- GitHub Actions publishes Python 0.2.0 to PyPI (when configured)
- Contract version updates to 0.2 across all docs

---

### Type 2: Language-Specific Patch Release

Use when fixing a bug in just one implementation.

**Example**: Fixing a Java-only timeout bug

```bash
# 1. Update java/lib/pom.xml version from 0.1.0 to 0.1.1
# 2. Update CHANGELOG.md:
#    ```
#    ### Java
#    - **0.1.1** (2026-06-15): Fixed connection timeout issue
#    ```
# 3. Update VERSIONS.md Java version to 0.1.1

git add java/lib/pom.xml CHANGELOG.md VERSIONS.md
git commit -m "fix(java): timeout issue in Redis connection"

# 4. Tag with language prefix
git tag java-v0.1.1
git push origin java-v0.1.1
```

**What happens:**
- GitHub Actions publishes ONLY Java 0.1.1 to Maven Central
- Python remains at 0.1.0
- Contract version stays 0.1

---

### Type 3: Python Patch Release

Same as Java, but with `python-v*` tag.

```bash
git tag python-v0.1.1
git push origin python-v0.1.1
```

---

## Prerequisites

### For First Release (Already Done ✓)

- [ ] GPG key created and published
- [ ] GitHub secrets configured:
  - `OSSRH_USERNAME`
  - `OSSRH_TOKEN`
  - `GPG_PRIVATE_KEY`
  - `GPG_PASSPHRASE`

### For Python Releases (Future)

- [ ] PyPI account created
- [ ] GitHub secrets for PyPI:
  - `PYPI_API_TOKEN`

---

## Checklist Before Each Release

### All Releases
- [ ] Update version in build files (pom.xml, setup.py, etc.)
- [ ] Update CHANGELOG.md
- [ ] Update VERSIONS.md
- [ ] Run tests locally: `mvn clean test` (Java) / `pytest` (Python)
- [ ] Commit changes
- [ ] Create git tag

### Contract Releases Only (v0.2)
- [ ] Ensure ALL implementations are ready
- [ ] Update all build files to X.Y.0
- [ ] Announce breaking changes (if any) in CHANGELOG

### Patch Releases Only (java-v0.1.1)
- [ ] Only update ONE language version
- [ ] Do NOT update contract version

---

## Verifying Published Artifacts

### Java (Maven Central)

After ~5 minutes:
```bash
mvn dependency:get -Dartifact=dev.kaiquebt:anycall:0.1.0:jar
```

Online:
- https://central.sonatype.com → search "dev.kaiquebt"
- https://search.maven.org → search "dev.kaiquebt anycall"

### Python (PyPI)

After ~5 minutes:
```bash
pip install anycall==0.1.0
```

Online:
- https://pypi.org/project/anycall/

---

## Troubleshooting

### Release workflow fails

1. Check GitHub Actions logs: https://github.com/KaiqueBahmad/anycall/actions
2. Common issues:
   - Missing/wrong secrets → add in Settings → Secrets
   - GPG key expired → regenerate and update secrets
   - Maven Central credentials invalid → regenerate User Token in Sonatype

### Artifact not appearing in Maven Central

- Wait ~5-10 minutes (Sonatype takes time to sync)
- Check Sonatype Central Portal for "Pending" status
- If stuck, click "Publish" button (if not automated)

### Version mismatch in CHANGELOG/VERSIONS

- Always commit version changes BEFORE tagging
- Tag should point to commit that updated versions
- If mistake: delete tag, fix commit, retag

---

## CI/CD Workflow Files

- `.github/workflows/test.yml` - Runs on every push to main (unit tests)
- `.github/workflows/release.yml` - Triggers on `v*` and `java-v*` tags (publishes to Maven Central)
- `.github/workflows/release-python.yml` - (TBD) Triggers on `python-v*` tags
