# Release Guide - AnyCall to Maven Central

## Overview
This guide explains how to publish AnyCall to Maven Central Repository using GitHub Actions and your GPG key.

## Prerequisites Completed ✓
- GPG key generated and published: `C375D904`
- GitHub Actions workflows configured (`.github/workflows/test.yml`, `release.yml`)
- Pom configuration ready (GPG signing, Central Publishing plugin)

## What You Need to Do Before First Release

### 1. Create Sonatype Account
1. Go to https://central.sonatype.com
2. Sign up with your email (kaiquebahmadt@gmail.com)
3. Create an account

### 2. Verify Namespace with Sonatype
Since `dev.kaiquebt` doesn't correspond to a domain you control, Sonatype will ask for verification via GitHub:
- Option A: Use GitHub identity (`io.github.kaiquebahmad` namespace)
- Option B: Control domain `kaiquebt.dev` and verify via DNS

**Recommended: Use Option A** (GitHub-based, simpler)
- The groupId for future releases would change to `io.github.kaiquebahmad:anycall`
- Or contact Sonatype JIRA to verify the existing `dev.kaiquebt` namespace through GitHub

### 3. Generate User Token
In your Sonatype Account settings:
1. Go to Account → Copy User Token (or similar menu)
2. You'll get a token like: `username` and `password`
3. Save these somewhere safe (password manager, etc.)

### 4. Add GitHub Secrets
Go to your GitHub repository: Settings → Secrets and Variables → Actions

Add these 4 secrets:
- `OSSRH_USERNAME` → the username from your User Token
- `OSSRH_TOKEN` → the password from your User Token
- `GPG_PRIVATE_KEY` → contents of `~/anycall-gpg-private.asc` (base64 encoded)
- `GPG_PASSPHRASE` → the passphrase you set when creating the GPG key

**Important: For `GPG_PRIVATE_KEY`**, encode it in base64:
```bash
cat ~/anycall-gpg-private.asc | base64 -w 0 > /tmp/gpg_b64.txt
# Copy contents of /tmp/gpg_b64.txt to GitHub secret
```

### 5. Ensure GPG Key is Public
Your key should already be on the keyserver. Verify:
```bash
gpg --keyserver keyserver.ubuntu.com --recv-keys C375D904
```

---

## How to Release (After Setup)

### Release v0.1.0
```bash
cd /path/to/anycall
git tag v0.1.0
git push origin v0.1.0
```

Then:
1. Go to https://github.com/KaiqueBahmad/anycall/actions
2. Watch the `Release` workflow execute
3. It will:
   - Compile lib module
   - Run tests
   - Sign all JARs with GPG
   - Upload to Sonatype Central Portal

### Verify Publication
After ~5 minutes:
- Check https://central.sonatype.com → search for `dev.kaiquebt:anycall`
- Status should be "Published" or "Pending"

After ~30 minutes (Central sync):
- Available at https://repo1.maven.org/maven2/dev/kaiquebt/anycall/0.1.0/
- Searchable on https://search.maven.org

### Test It
```bash
mvn dependency:get -Dartifact=dev.kaiquebt:anycall:0.1.0:jar
```

---

## Troubleshooting

### Release workflow fails with "credentials invalid"
- Check `OSSRH_USERNAME` and `OSSRH_TOKEN` secrets are correct in GitHub
- Verify you generated them from Sonatype Central Portal
- Note: User Token ≠ your account password

### GPG signature fails
- Verify `GPG_PASSPHRASE` is correct
- Verify `GPG_PRIVATE_KEY` is properly base64 encoded
- Check if key is still in `gpg --list-keys`

### Namespace verification fails
- Contact Sonatype support via https://issues.sonatype.org
- Request namespace verification for `dev.kaiquebt`
- Alternatively, migrate to `io.github.kaiquebahmad` namespace

---

## Future Releases

Version pattern: `vX.Y.Z` (semantic versioning)

```bash
git tag v0.2.0
git push origin v0.2.0
# GitHub Actions handles the rest automatically
```

All artifacts will be signed with your GPG key and published to Maven Central.

---

## Important Notes

1. **Version format**: `X.Y.Z` (no SNAPSHOT, no extra suffixes)
2. **Module scope**: Only `lib` (dev.kaiquebt:anycall) is published; examples are excluded
3. **SCM info**: Already configured in `java/lib/pom.xml`
4. **Test coverage**: GitHub Actions will run tests before every release
5. **GPG key backup**: You have `~/anycall-gpg-private.asc` and a revocation cert in `~/.gnupg/openpgp-revocs.d/`
