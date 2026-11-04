# Doist fork of dbt-adapters

This repository is the Todoist fork of `dbt-labs/dbt-adapters`. It carries patches to the dbt-athena adapter that the `Doist/data` dbt project needs and that upstream has not released. We build only the dbt-athena wheel. We attach it to a GitHub release, and `Doist/data` pins it by URL and sha256.

## Branches

1. `main` tracks upstream `main`. We never commit to it, so each upstream pull request branch diffs cleanly against upstream.
2. `doist/<X.Y>`, for example `doist/1.11`, is the carry branch. It starts at the upstream commit that set dbt-athena to the release version, for example `1.11.1`.
3. `upstream/<slug>` holds one patch in the shape that upstream wants. We cut it from `main`, one branch for each upstream pull request.

## Commits on the carry branch

The commits are in this order:

1. One commit for each patch, named `<nn>/<slug>`.
   `<nn>` is the number of the problem in the Doist problem register. Thus a rebase conflict points to its problem file.
2. `doist/drop-upstream-workflows`: deletes the upstream automation (see [Actions on the fork](#actions-on-the-fork)).
3. `doist/release-workflow`: the release workflow and this file.
4. `doist/version-<X.Y.Z>+doist.<N>`: the version line in `dbt-athena/src/dbt/adapters/athena/__version__.py`.

A fix to a patch goes into the commit of that patch (`git commit --fixup`, then `git rebase --autosquash`). Do not add a separate fix commit.

## Rules for the fork

1. Never pin a `main` version. Always use an upstream release plus `+doist.<N>`, with the URL source.
2. Keep one commit for each patch on the carry branch, named `<nn>/<slug>` after the problem register.
3. When upstream merges a patch, remove the patch from the carry branch at the next rebase. Do not keep it as a safeguard.
4. Do not post to upstream without Giuliano. The drafts are in the problem files.

## Versions and tags

1. The version is `<X.Y.Z>+doist.<N>`.
   1. `<X.Y.Z>` is the upstream release that the carry branch starts from.
   2. `<N>` counts the fork releases on that upstream release, from 1.
2. The tag is `dbt-athena-v<X.Y.Z>+doist.<N>`, for example `dbt-athena-v1.11.1+doist.1`. Upstream tags start with `v`, so our tags cannot collide with them.
3. GitHub keeps the `+` in the asset name. The download URL encodes it as `%2B`:
   `https://github.com/Doist/dbt-adapters/releases/download/dbt-athena-v1.11.1%2Bdoist.1/dbt_athena-1.11.1%2Bdoist.1-py3-none-any.whl`

## Actions on the fork

Only `doist-release-dbt-athena.yml` runs on the fork. A tag push runs it from the tagged commit. It runs the unit tests, then builds and releases the wheel.

The commit `doist/drop-upstream-workflows` deletes the upstream automation: workflows, actions, filters, Dependabot and `CODEOWNERS`. `main` keeps these files, because it stays equal to upstream. `main` is the default branch, and GitHub runs scheduled, issue and `pull_request_target` workflows from the default branch. Set up the fork like this:

1. Enable workflows in the Actions tab of the fork. GitHub lists the workflows of a fork only after this step.
2. Immediately disable each upstream workflow:

   ```sh
   gh workflow list --repo Doist/dbt-adapters --all --json id,path,state \
     --jq '.[] | select(.state == "active" and (.path | startswith(".github/workflows/")) and (.path | endswith("/doist-release-dbt-athena.yml") | not)) | .id' |
     xargs -n 1 gh workflow disable --repo Doist/dbt-adapters
   ```

Do step 2 again after each sync of `main`, because GitHub enables a new workflow file.

A rebase stops when upstream changed a file that the carry branch deleted. Delete the file again with `git rm <file>`, then run `git rebase --continue`.

## Cut a release

1. On the carry branch, change the version commit to the new version, for example `1.11.1+doist.2`. Change the commit name to match.
2. In `dbt-athena/`, run the unit tests: `hatch run unit-tests`.
3. Tag the head of the carry branch and push the branch and the tag:

   ```sh
   git tag 'dbt-athena-v1.11.1+doist.2' doist/1.11
   git push --force-with-lease origin doist/1.11
   git push origin 'dbt-athena-v1.11.1+doist.2'
   ```

4. The workflow runs the unit tests and builds the wheel. It stops if the wheel version is not equal to the version in the tag. Then it makes the release and attaches the wheel. The release notes give the pin for `Doist/data`.
5. In `Doist/data`, change the pin in `dbt/pyproject.toml` (the version and the URL), then run `uv lock` in `dbt/`. Open a pull request.

Old tags keep the old commits, so a force push of the carry branch does not break a released wheel.

## Rebase onto a new upstream release

Rebase only when an upstream release has a thing that we want. That is a merged version of one of our patches, or a fix that we need. Read the dbt-athena changelog at each upstream release.

1. Fetch upstream: `git fetch upstream`.
2. Find the commit on upstream `stable` that sets `dbt-athena/src/dbt/adapters/athena/__version__.py` to the new release.
3. Make the new carry branch and rebase onto that commit:

   ```sh
   git switch -c doist/1.12 doist/1.11
   git rebase --onto <release commit> <old base commit> doist/1.12
   ```

4. Remove each patch commit that upstream now contains.
5. In `dbt-athena/`, run `hatch run unit-tests`.
6. Do the write tests in the data playground again for each problem whose files changed.
7. Do the access check again. A reader without access to personal data must see no personal columns and no untagged tables.
8. Change the version commit to `<new release>+doist.1`, then cut a release as above.
9. In `Doist/data`, follow the upgrade checklist of problem 11. After the deploy, Giuliano changes `StartupScriptS3ObjectVersion`.
