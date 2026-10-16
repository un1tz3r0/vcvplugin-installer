# Security policy

## Supported versions

Only the [latest release](https://github.com/un1tz3r0/vcvplugin-installer/releases/latest) receives security fixes.

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/un1tz3r0/vcvplugin-installer/security/advisories/new),
not in a public issue. Include the version, a description, and if possible a package file or steps that reproduce
it.

## Scope

The installer unpacks archives downloaded from the internet into your home directory, so these are in scope:

- a package that makes the installer write, overwrite or delete files outside the Rack plugins folder
  (it is meant to reject absolute paths, `..` components, links and device files)
- a package that makes it install into a different plugin's folder than the one its `plugin.json` names
- crashes or hangs caused by a malformed package

The plugin code itself runs inside VCV Rack, and the installer does not vet it: install plugins only from sources
you trust.
