# Release Guide - AnyCall Polyglot Versioning

This guide explains how to release AnyCall following the polyglot versioning model.

## Version Model

- **Contract Version (X.Y)**: Synchronized API across all languages
- **Patch Version (Z)**: Independent bug fixes per language
- **Protocol Version**: what's on Redis ([PROTOCOL.md](PROTOCOL.md)). It's
  the contract version of the release that last changed the protocol, and it
  only moves on such a release: one that changes keys, messages, scripts or
  constants. Implementations that speak the same protocol version can share a
  Redis.

Example:
- Java: 1.2.0, 1.2.1, 1.2.2
- Python: 1.2.0, 1.2.1
- All are **contract 1.2**, fully compatible
- If 1.2 changed the protocol and 1.3 didn't, both speak **protocol 1.2**,
  and a 1.2 client can call a 1.3 server. A 1.4 that changes it speaks
  protocol 1.4, which neither 1.2 nor 1.3 can share a Redis with.

A contract release that changes the protocol updates the version in
`PROTOCOL.md`'s title; one that doesn't leaves it, and its CHANGELOG section
says which protocol it speaks.

> **Note:** per SemVer, `0.Y.Z` is unstable. The contract and internal working is still not well defined, so it can vary a lot between versions.

## Release Types

### Type 1: Contract Release (New API Version)

Use when adding features or making changes that affect all implementations.

**Example**: Releasing contract 1.3 with new RPC features

```bash
# 1. CHANGELOG.md: [Unreleased] becomes [1.3] - <date>; it says which protocol
#    1.3 speaks
# 2. Python's version, the one place a version is written down (Java's and
#    anycall-spring's come from the tag):
#    implementations/python/lib/pyproject.toml, implementations/python/uv.lock
#    and tools/visualizer/uv.lock to 1.3.0
# 3. Only if 1.3 changes the protocol: PROTOCOL.md's title to Protocol 1.3

git add CHANGELOG.md implementations/python/lib/pyproject.toml \
    implementations/python/uv.lock tools/visualizer/uv.lock
git commit -m "chore(release): bump contract to 1.3"

# 4. Tag and push
git tag v1.3
git push origin v1.3
```

**What happens:**
- GitHub Actions publishes Java 1.3.0 to Maven Central
- GitHub Actions publishes `anycall-spring` 1.3.0 to Maven Central, bringing in anycall 1.3.0
- GitHub Actions publishes Python 1.3.0 to PyPI and makes the GitHub release
- Each Maven Central deployment then waits to be published in the Central portal

---

### Type 2: Language-Specific Patch Release

Use when fixing a bug in just one implementation.

**Example**: Fixing a Java-only timeout bug

```bash
# 1. Commit the fix on the branch of contract 1.2: main while 1.2 is the
#    latest, or release/1.2 (made from the v1.2 tag) once it isn't
# 2. Tag with the language prefix; the version comes from the tag
git tag java-v1.2.1
git push origin java-v1.2.1
```

**What happens:**
- GitHub Actions publishes ONLY Java 1.2.1 to Maven Central
- Python remains at 1.2.0
- Contract version stays 1.2

---

### Type 3: Python Patch Release

Same as Java, but with `python-v*` tag.

```bash
git tag python-v1.2.1
git push origin python-v1.2.1
```

---

### Type 4: Spring Patch Release

Use when fixing `anycall-spring` (`integrations/spring`), or to make it bring in
a newer anycall patch. Its patch number is its own: `anycall-spring` 1.2.1 may
bring in anycall 1.2.3.

```bash
git tag spring-v1.2.1
git push origin spring-v1.2.1
```

**What happens:**
- GitHub Actions finds the newest anycall 1.2.x on Maven Central and publishes
  `anycall-spring` 1.2.1 bringing it in
- It fails if no anycall 1.2.x is on Maven Central yet

---

## Checklist Before Each Release

### All Releases
- [ ] Run tests locally: `mvn clean install` in `implementations/java` (lib, `anycall-spring`, examples) / `uv run pytest` in `implementations/python/lib`
- [ ] Commit changes
- [ ] Create git tag
- [ ] Publish each Maven Central deployment in the Central portal

### Contract Releases Only (v1.3)
- [ ] Ensure ALL implementations are ready
- [ ] CHANGELOG.md: date the section and say which protocol it speaks
- [ ] Python's version (pyproject.toml and both uv.lock) to X.Y.0
- [ ] PROTOCOL.md's title, only if the protocol changed
- [ ] Announce breaking changes (if any) in CHANGELOG

### Patch Releases Only (java-v1.2.1, python-v1.2.1, spring-v1.2.1)
- [ ] Only update ONE language version
- [ ] Do NOT update contract version

---

## Verifying Published Artifacts

### Java (Maven Central)

After ~5 minutes:
```bash
mvn dependency:get -Dartifact=dev.kaiquebt:anycall:1.2.0:jar
```

Online:
- https://central.sonatype.com → search "dev.kaiquebt"
- https://search.maven.org → search "dev.kaiquebt anycall"

### Python (PyPI)

After ~5 minutes:
```bash
pip install anycall==1.2.0
```

Online:
- https://pypi.org/project/anycall/

---

## CI/CD Workflow Files

- `.github/workflows/release-contract.yml` - Triggers on `vX.Y` tags: publishes Java and `anycall-spring` X.Y.0 to Maven Central and Python X.Y.0 to PyPI, and makes the GitHub release
- `.github/workflows/release-java.yml` - Triggers on `java-v*` tags: publishes a Java patch
- `.github/workflows/release-python.yml` - Triggers on `python-v*` tags: publishes a Python patch
- `.github/workflows/release-spring.yml` - Triggers on `spring-v*` tags: publishes an `anycall-spring` patch
- `.github/workflows/test-spring.yml` - Runs on pushes and PRs that touch the Java lib or `integrations/spring`: `anycall-spring`'s tests on Spring Boot 3.5 and 4
