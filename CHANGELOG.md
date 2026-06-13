# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-13

### Added

- Database introspection locks to prevent concurrent schema introspection conflicts.

### Changed

- Optimized TUI rendering using asynchronous chunked feeding to improve frame rates and typing responsiveness in the results table.
- Limited command palette results to the top 15 matches to improve filtering performance.
- Pre-compiled regular expressions in the status bar to reduce render-pass CPU overhead.
- Cached logger instances on first use to improve structured log performance.

### Fixed

- Fixed release workflow checksum and artifact packaging selectors.
- Fixed setup-uv setup caching in GitHub Actions CI and release workflows.

## [0.1.0] - 2026-06-10

### Added

- First implementation of Teridex.