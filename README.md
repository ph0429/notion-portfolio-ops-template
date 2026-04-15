# Notion Portfolio Ops Template

A template for running a private portfolio editorial workflow on top of Notion, OpenAI, and GitHub Actions.

This template is designed for people who:

- do meaningful work in one Notion workspace
- want to turn that work into portfolio-ready drafts in a separate private workspace
- want a review-and-approval layer before anything reaches live portfolio pages

## What It Does

The system is split into three workflows:

1. `weekly-review`
   - scans source-workspace pages you created or edited
   - uses OpenAI to decide whether they are portfolio-worthy
   - writes recommendations into a review inbox database

2. `apply-approved`
   - reads inbox rows you have explicitly approved
   - stages them as private draft pages in a publish queue database

3. `reconcile-portfolio`
   - compares approved candidates against live portfolio pages and other approved items
   - writes merge / keep separate / archive suggestions into a reconciliation queue

## Suggested Notion Structure

- `Portfolio Sync Inbox`
  Review queue for recommendations generated from source work.

- `Portfolio Publish Queue`
  Private staging area for approved draft pages.

- `Portfolio Reconciliation Queue`
  Editorial decision queue for overlap, merging, and deduplication.

- `Portfolio DB`
  Your curated live portfolio pages.

## Workflow

1. Run `weekly-review`
2. Review rows in `Portfolio Sync Inbox`
3. Set strong rows to `approved`
4. Run `apply-approved`
5. Review and refine staged drafts in `Portfolio Publish Queue`
6. Run `reconcile-portfolio`
7. Use the reconciliation queue to decide what should merge, stay separate, or be archived
8. Manually update the live `Portfolio DB`

## Why This Repo Is Useful

This template shows a practical pattern for:

- structured AI-assisted portfolio extraction
- approval-gated publishing workflows
- safe staging before live updates
- editorial reconciliation of overlapping content

It is intentionally designed so automation does not write straight into live public-facing pages without a review layer.

## Local Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

Run the flows:

```bash
portfolio-ops review sync --mode bootstrap
portfolio-ops review sync --mode incremental
portfolio-ops apply sync --mode approved
portfolio-ops reconcile sync --mode approved
```

## GitHub Actions

This repo includes three workflows:

- `.github/workflows/weekly-review.yml`
- `.github/workflows/apply-approved.yml`
- `.github/workflows/reconcile-portfolio.yml`

They are designed to run against repository secrets for Notion tokens, database IDs, and an OpenAI API key.

## Configuration

See `.env.example` for the required environment variables.

## Safety Model

- recommendations are reviewed before being applied
- approved items are staged privately before publication
- reconciliation is a separate editorial pass
- live portfolio pages remain under human control
