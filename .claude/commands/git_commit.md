---
description: Commit staged changes to git following project conventions
---

# Git Commit Command

Please commit the currently staged changes to git following the existing commit message conventions used in this repository.

Instructions:
1. First, run `git status` to see the current state of the repository
2. If there are unstaged changes that appear to be from recent work:
   - Check if they are related to the current task/conversation
   - Stage only the relevant files explicitly (use `git add <file>` for specific files)
   - NEVER use `git add -A` blindly - be selective about what to stage
   - If unsure whether to stage a file, ask the user first
3. Run `git diff --staged` to see what changes will be committed
4. Analyze the changes to understand what they accomplish
5. Create a descriptive commit message following the project's conventions (see below)
6. Execute the commit with the appropriate message

## Commit Message Conventions

This project follows the Conventional Commits format with these specific patterns:

### Format Structure
```
<type>[(scope)]: <subject>

<body with bullet points>
```

### Commit Types
- `feat:` - New features or significant enhancements
- `refactor:` - Code restructuring without changing external behavior
- `fix:` - Bug fixes
- `chore:` - Maintenance tasks (cleanup, dependencies, configuration)
- `test:` - Test additions or modifications
- `docs:` - Documentation changes

### Scope (optional but common)
- Use parentheses when targeting specific subsystems: `refactor(tests):`, `feat(jets):`, `chore(deps):`
- Omit scope for broad cross-cutting changes

### Subject Line
- Capitalize the first word
- Use imperative mood ("Add feature" not "Added feature")
- No period at the end
- Keep concise but descriptive

### Body Format
- Leave a blank line after the subject
- Use bullet points (with `-` prefix) for multiple changes
- Each bullet should be a complete, capitalized sentence ending with a period
- Focus on WHAT changed and WHY, not HOW
- Group related changes together

### Examples from This Project
```
feat: Introduce `WaveformTrait` for backend-agnostic waveform loading

- Added `WaveformTrait` to unify file loading across backends.
- Implemented `WellenWaveform` and `JetsWaveform` backends.
- Centralized backend logic with factory function for format detection.
- Maintained Python API stability with no breaking changes.
```

```
refactor(tests): Replace explicit waits with `qtbot.waitUntil`

- Updated tests to use `qtbot.waitUntil` for reliable async waiting.
- Replaced redundant `QTest.qWait` calls with `QApplication.processEvents`.
- Streamlined event handling in paste and grouping tests.
```

```
chore: Remove pyjets library and related tests

- Deleted `pyjets` library and GPU simulator implementation.
- Removed associated tests and configuration files.
- Cleaned up dependencies for streamlined codebase.
```

Do not push the commit unless explicitly requested.
