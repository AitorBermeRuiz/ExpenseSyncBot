---
agent: agent
---

Read the changes introduced on the current branch, including BOTH:

1. Uncommitted workspace modifications (staged and unstaged)
2. Committed changes that are on the current HEAD but not yet in the default upstream branch (e.g. `origin/main`)

Guidance:

- First, capture uncommitted diffs (equivalent of `git diff` and `git diff --cached`).
- Then, determine the merge base with the default branch (assume `origin/main` unless configured otherwise) using `git merge-base HEAD origin/main` and diff (`git diff <merge-base>...HEAD`) to include committed-but-unpushed work.



Be concise and conservative: only suggest changes that are absolutely necessary.