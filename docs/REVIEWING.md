# How packs are reviewed

Every listing is reviewed by a person after the automated checks pass. This page is the maintainer's guide, and it's
public so makers know what to expect.

## Principles

- **One exact commit.** A review covers the commit in the entry and nothing else. A later commit is a new review.
- **Evidence, not impressions.** Each finding names the file and lines, or the moment in the pack, and says what
  happens because of it.
- **A clear next step.** Every reply ends with what's needed: approval, a specific change, or a decision.
- **Only what's true and verified.** A review says what was checked and what wasn't. Passing the checks is not a
  claim that a pack is flawless.

## Updates

An update is reviewed like a new listing, but only for what changed: the checks list the files that changed between
the approved commit and the new one, and the review covers those, the new preview, and any changed fields. The
previous version stays listed until the update is approved, and stays listed if it isn't.

## Delisting

A pack is delisted only for a reason in [CONTRIBUTING.md](../CONTRIBUTING.md#delisting), after its maker has had 30
days to fix it, or straight away for a rights or safety problem or at its maker's request. A maker pushing new work to
their repository is never a reason: the catalog lists the approved commit, not the branch.

## Replies

Each reply uses the same layout, so makers can find what matters at a glance.

### Approved

```markdown
**Approved:** `aquarium` at `4f1c2e9…` (full SHA)

**Checked**
- Catalog checks passed on this commit: 960 × 540 and 2304 × 1440, whole loop, no flashes; slowest frame 12 ms.
- Rights: all art drawn by the author (provenance in the entry); license CC-BY-4.0, in the repository's root.
- Content and impersonation: nothing found.
- Preview: matches the pack at 14 s.

**Listed** once merged. Updates are reviewed the same way, by commit.
```

### Changes needed

```markdown
**Changes needed:** `aquarium` at `4f1c2e9…` (full SHA)

**Findings**
1. `screensafe.toml:42-48`: the "bubbles" element covers the whole screen at 0.9 opacity from 31 s to 33 s,
   so the pack looks like a blank screen for two seconds. Please fade it or shrink it.
2. `fonts/Display.ttf`: no license is given for this font. Please add its license file, or use a font
   whose license allows redistribution.

**Next:** push the fixes, update `commit` in the entry to the new full SHA, and the checks and review will run again.
```

### Not listed

```markdown
**Not listed:** `aquarium` at `4f1c2e9…` (full SHA)

**Reason**
- The pack shows a likeness of a real person (`faces.png`, frames 3 to 8) without their consent.

This decision is about this pack, not about you. You're welcome to submit another.
```

### Delisted

```markdown
**Delisted:** `aquarium`, listed at `4f1c2e9…` (full SHA), on 2026-12-01

**Reason**
- The weekly check has failed since 2026-10-28: the approved commit can no longer be fetched (the repository
  returns 404). Its maker was told on 2026-10-28 and in a reminder on 2026-11-18.

**To relist:** restore the repository, or submit the pack from its new home, as a new pull request.
```
