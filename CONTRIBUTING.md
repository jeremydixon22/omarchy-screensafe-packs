# Listing a pack

Thank you for sharing a screensaver. Listing one takes a pull request that adds a few lines to `packs.toml`; checks
run on it automatically, and a person reviews it.

## 1. Make and check the pack

[Making a screensaver](https://github.com/jeremydixon22/omarchy-screensafe/blob/main/docs/MAKING.md) is the way in, and
ScreenSafe's agent skill can walk a coding agent through it. Before you submit, check the pack at two sizes, with no
flashes reported. These commands cover the first 600 seconds, or the whole loop if shorter; disclose any longer
portion that these checks do not cover for additional review:

```sh
screensafe=~/.config/omarchy/plugins/io.github.jeremydixon22.screensafe/bin/screensafe-$(uname -m)
$screensafe check path/to/pack --seconds 600
$screensafe check path/to/pack --seconds 600 --size 2304x1440
$screensafe render path/to/pack --time 12 --size 1920x1080 --out path/to/pack/preview.png
```

## 2. Publish it

Put the pack in a public GitHub repository you control: a repository of its own, a theme's `screensafe/` folder, or a
folder among others. At the commit you submit, the pack's folder holds:

- `screensafe.toml`, whose `name`, `license` and `description` your entry repeats exactly;
- its preview, a frame from `screensafe render` that shows what the pack really looks like;
- only `.toml`, `.txt`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.ttf` and `.otf` files, plus `LICENSE` or `README.md`, with
  no links, at most 96 MiB in all. Hidden files and folders are never installed;
- a `LICENSE` (CC0-1.0, CC-BY-4.0 or MIT), in the pack's folder or at the repository's root.

Strip metadata from images before you commit them.

## 3. Add its entry

Fork this repository, add your `[[pack]]` to `packs.toml` in order of `id` (the example at the top shows every field),
and run:

```sh
python3 scripts/catalog.py generate
python3 scripts/catalog.py verify your-pack-id
```

`verify` fetches your pack exactly as people will install it and checks it with ScreenSafe's renderer. Commit
`packs.toml` with the pages `generate` wrote, and open a pull request. Change nothing else.

## 4. Review

The checks run on your pull request. A maintainer then looks at:

- **rights:** the license, where every image, font or likeness comes from (including generated material), and any
  trademarks. Likenesses of real people need their consent;
- **content:** nothing hateful, sexual, gory or shocking. A screensaver appears on its own, in offices and shared rooms;
- **impersonation:** nothing that looks like a lock screen, a login or password prompt, or a system dialog, and no
  instructions to run commands;
- **photosensitivity:** a second look at anything close to the flash limit;
- **the preview:** that it shows what the pack really looks like.

Replies follow the layouts in [How packs are reviewed](docs/REVIEWING.md): what was checked, each finding with its
file and lines, and what's needed next. Approval is of the exact commit in your entry.

## Keep the approved commit reachable

People install the exact commit in your entry, so it has to stay in your repository. GitHub can drop a commit that no
branch or tag points to, after a force-push, a rebase, or a deleted branch. The simplest guard is a tag on each
approved commit:

```sh
git tag screensafe-aquarium-1 4f1c…   # your pack's id, and a number for each listed version
git push origin screensafe-aquarium-1
```

## Updating your pack

Work in your repository as usual: push to `main`, use branches, whatever suits you. Nothing you push changes what
people install, which stays the approved commit until an update is approved. When a new version is ready:

1. Run the checks in step 1 on it, and render a new preview if it changed.
2. Open a pull request changing your entry's `commit` (and `name`, `description`, `license` or `preview`, if they
   changed), with the pages `generate` writes. The checks list the files that changed since the approved commit.
3. It's reviewed like a new listing, but only for what changed. Until it's approved, the catalog keeps listing your
   previous version, so nobody is ever left with a broken install.

The new commit can be on any branch or tag of your repository, as long as it stays reachable once approved.

## Delisting

Every listed pack is checked again each week, at its approved commit. Pushing new work to your repository never
affects it. A pack is flagged in an issue, and delisted if it isn't fixed within 30 days, only when:

- its repository or its approved commit can no longer be fetched (restore it, or submit an update pointing to a
  commit that's reachable); or
- it no longer passes the checks, for example after a change to ScreenSafe's format, which is announced to makers in
  good time. You can ask for your own pack to be delisted at any time, and it
will be, no questions asked. A rights or safety problem is delisted first and discussed after.
