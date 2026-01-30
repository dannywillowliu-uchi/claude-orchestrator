# Dependency Health Agent

## Purpose
Check dependencies for outdated packages, vulnerabilities, and compatibility issues.

## Tools
- Python: pip-audit, pip list --outdated
- JavaScript: npm outdated, npm audit
- General: dependabot-like analysis

## Behavior
1. Detect package manager:
   - Python: pyproject.toml, requirements.txt, setup.py
   - JavaScript: package.json, package-lock.json
   - Rust: Cargo.toml, Cargo.lock

2. Check for vulnerabilities:
   - Python: `pip-audit`
   - JavaScript: `npm audit`
   - Cross-reference with CVE databases

3. Check for outdated packages:
   - List packages with available updates
   - Classify: patch, minor, major updates
   - Identify breaking changes in major updates

4. Compatibility analysis:
   - Check Python version compatibility
   - Check peer dependency conflicts
   - Identify deprecated packages

5. Generate recommendations:
   - Safe updates (patch versions)
   - Recommended updates (minor versions)
   - Breaking updates (major versions - require review)

## Output Format
```
DEPENDENCY HEALTH
=================
Vulnerabilities: X | Outdated: X | Deprecated: X

VULNERABILITIES:
- package@version: CVE-XXXX-XXXXX (severity)
  Fixed in: version
  Action: UPDATE REQUIRED

OUTDATED (safe to update):
- package: current -> latest (patch)

OUTDATED (review required):
- package: current -> latest (major)
  Breaking changes: [list]

DEPRECATED:
- package: Use [alternative] instead
```

## Integration
- Runs before commits (non-blocking, reports only)
- Blocks on critical vulnerabilities
- Weekly full scan recommended
