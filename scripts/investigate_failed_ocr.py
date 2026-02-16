#!/usr/bin/env python3
"""Investigate sites with no completed OCR documents.

This script helps diagnose why 50+ sites show "No completed OCR documents found".
Checks filesystem, database state, and RQ job history to understand what happened.
"""

from pathlib import Path

import click
from sqlalchemy import select

from clerk.db import civic_db_connection
from clerk.models import sites_table
from clerk.settings import get_env


def investigate_site(subdomain: str) -> dict:
    """Investigate a single site's OCR failure.

    Returns:
        dict with diagnostic information
    """
    storage_dir = get_env("STORAGE_DIR", "../sites")
    site_dir = Path(f"{storage_dir}/{subdomain}")

    result = {
        "subdomain": subdomain,
        "site_dir_exists": site_dir.exists(),
        "pdf_count": 0,
        "pdf_files": [],
        "txt_base_exists": False,
        "txt_structure": {},
        "has_any_txt_files": False,
        "db_state": {},
    }

    # Check PDFs
    pdf_dir = site_dir / "pdfs"
    if pdf_dir.exists():
        pdf_files = list(pdf_dir.glob("**/*.pdf"))
        result["pdf_count"] = len(pdf_files)
        result["pdf_files"] = [str(p.relative_to(site_dir)) for p in pdf_files[:5]]  # First 5

    # Check txt directory structure
    txt_base = site_dir / "txt"
    result["txt_base_exists"] = txt_base.exists()

    if txt_base.exists():
        # Check if any txt files exist at all (even in wrong structure)
        all_txt_files = list(txt_base.glob("**/*.txt"))
        result["has_any_txt_files"] = len(all_txt_files) > 0

        # Map out the directory structure
        for item in txt_base.iterdir():
            if item.is_dir():
                meeting_name = item.name
                result["txt_structure"][meeting_name] = []
                for doc_dir in item.iterdir():
                    if doc_dir.is_dir():
                        txt_files = list(doc_dir.glob("*.txt"))
                        result["txt_structure"][meeting_name].append(
                            {
                                "dir": doc_dir.name,
                                "txt_count": len(txt_files),
                                "has_files": len(txt_files) > 0,
                            }
                        )

    # Check database state
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

        if site:
            result["db_state"] = {
                "current_stage": site.current_stage,
                "ocr_total": site.ocr_total,
                "ocr_completed": site.ocr_completed,
                "ocr_failed": site.ocr_failed,
                "coordinator_enqueued": site.coordinator_enqueued,
                "last_error_stage": site.last_error_stage,
                "last_error_message": site.last_error_message,
                "updated_at": str(site.updated_at) if site.updated_at else None,
            }

    return result


@click.command()
@click.option("--limit", default=10, help="Number of failed sites to investigate")
def main(limit):
    """Investigate sites with no completed OCR documents."""

    click.echo("=" * 80)
    click.echo("INVESTIGATION: Sites with No Completed OCR Documents")
    click.echo("=" * 80)
    click.echo()

    # Find sites with ocr_completed = 0
    with civic_db_connection() as conn:
        failed_sites = conn.execute(
            select(sites_table).where(
                sites_table.c.current_stage == "ocr",
                sites_table.c.ocr_completed == 0,
            )
        ).fetchall()

    click.echo(f"Found {len(failed_sites)} sites with ocr_completed = 0")
    click.echo()

    if not failed_sites:
        click.echo("No sites found with zero completed OCR documents")
        return

    # Investigate first N sites
    for i, site in enumerate(failed_sites[:limit]):
        click.echo(f"Site {i+1}/{min(limit, len(failed_sites))}: {site.subdomain}")
        click.echo("-" * 80)

        info = investigate_site(site.subdomain)

        # Database state
        click.echo("Database:")
        click.echo(f"  current_stage: {info['db_state'].get('current_stage')}")
        click.echo(f"  ocr_total: {info['db_state'].get('ocr_total')}")
        click.echo(f"  ocr_completed: {info['db_state'].get('ocr_completed')}")
        click.echo(f"  ocr_failed: {info['db_state'].get('ocr_failed')}")
        if info["db_state"].get("last_error_message"):
            click.echo(f"  last_error: {info['db_state'].get('last_error_message')[:100]}")

        # Filesystem state
        click.echo("Filesystem:")
        click.echo(f"  site_dir exists: {info['site_dir_exists']}")
        click.echo(f"  pdf_count: {info['pdf_count']}")
        if info["pdf_files"]:
            click.echo(f"  sample PDFs: {info['pdf_files'][:3]}")
        click.echo(f"  txt_base exists: {info['txt_base_exists']}")
        click.echo(f"  has_any_txt_files: {info['has_any_txt_files']}")

        # Txt structure analysis
        if info["txt_structure"]:
            click.echo("  txt structure:")
            for meeting, docs in info["txt_structure"].items():
                docs_with_files = sum(1 for d in docs if d["has_files"])
                total_docs = len(docs)
                click.echo(f"    {meeting}: {docs_with_files}/{total_docs} docs with txt files")
                if docs_with_files == 0 and total_docs > 0:
                    # All docs in this meeting have no txt files
                    click.secho(f"      ⚠️ {total_docs} document dirs but no txt files!", fg="yellow")

        # Diagnosis
        click.echo("Diagnosis:")
        if not info["site_dir_exists"]:
            click.secho("  ❌ Site directory doesn't exist - storage issue", fg="red")
        elif info["pdf_count"] == 0:
            click.secho("  ⚠️ No PDFs found - fetch stage may have failed", fg="yellow")
        elif not info["txt_base_exists"]:
            click.secho("  ⚠️ No txt directory - OCR never ran or output lost", fg="yellow")
        elif info["has_any_txt_files"]:
            click.secho(
                "  ⚠️ Has txt files but wrong structure - check txt_structure above", fg="yellow"
            )
        else:
            click.secho("  ❌ OCR truly failed for all documents", fg="red")

        click.echo()

    # Summary statistics
    click.echo("=" * 80)
    click.echo("SUMMARY")
    click.echo("=" * 80)

    patterns = {
        "no_site_dir": 0,
        "no_pdfs": 0,
        "no_txt_base": 0,
        "has_txt_wrong_structure": 0,
        "true_ocr_failure": 0,
    }

    for site in failed_sites[:limit]:
        info = investigate_site(site.subdomain)

        if not info["site_dir_exists"]:
            patterns["no_site_dir"] += 1
        elif info["pdf_count"] == 0:
            patterns["no_pdfs"] += 1
        elif not info["txt_base_exists"]:
            patterns["no_txt_base"] += 1
        elif info["has_any_txt_files"]:
            patterns["has_txt_wrong_structure"] += 1
        else:
            patterns["true_ocr_failure"] += 1

    click.echo(f"Patterns found (from {limit} sites investigated):")
    click.echo(f"  No site directory: {patterns['no_site_dir']}")
    click.echo(f"  No PDFs found: {patterns['no_pdfs']}")
    click.echo(f"  No txt directory: {patterns['no_txt_base']}")
    click.echo(f"  Has txt files but wrong structure: {patterns['has_txt_wrong_structure']}")
    click.echo(f"  True OCR failure (all docs failed): {patterns['true_ocr_failure']}")
    click.echo()

    if patterns["true_ocr_failure"] > 0:
        click.echo("Recommendations:")
        click.echo("  - Check last_error_message for common error patterns")
        click.echo("  - Consider re-enqueueing OCR jobs for these sites")
        click.echo("  - Investigate if PDFs are corrupted or need special handling")


if __name__ == "__main__":
    main()
