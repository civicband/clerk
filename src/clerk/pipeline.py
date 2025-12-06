"""ETL pipeline orchestration and component lookup."""

import datetime
import json
from typing import Any

from .adapter import FetcherAdapter
from .defaults import GenericLoader, IdentityTransformer
from .utils import pm


def lookup_extractor(label: str) -> type | None:
    """Look up an extractor class by label.

    Args:
        label: The extractor label to look up.

    Returns:
        The extractor class, or None if not found.
    """
    results = pm.hook.extractor_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def lookup_transformer(label: str) -> type | None:
    """Look up a transformer class by label.

    Args:
        label: The transformer label to look up.

    Returns:
        The transformer class, or None if not found.
    """
    results = pm.hook.transformer_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def lookup_loader(label: str) -> type | None:
    """Look up a loader class by label.

    Args:
        label: The loader label to look up.

    Returns:
        The loader class, or None if not found.
    """
    results = pm.hook.loader_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def get_pipeline_components(site: dict[str, Any]) -> dict[str, type] | FetcherAdapter:
    """Get ETL pipeline components for a site.

    If the site has a pipeline JSON config, looks up each component
    and uses defaults for missing ones.

    If the site only has a scraper field, wraps the old-style fetcher
    in a FetcherAdapter for backward compatibility.

    Args:
        site: Site configuration dictionary.

    Returns:
        Either a dict of component classes (extractor, transformer, loader)
        or a FetcherAdapter wrapping an old-style fetcher.

    Raises:
        ValueError: If required components are not found or site has
                    neither pipeline nor scraper configured.
    """
    pipeline_json = site.get("pipeline")

    if pipeline_json:
        pipeline = json.loads(pipeline_json)

        # Look up extractor (required)
        extractor_label = pipeline.get("extractor")
        if extractor_label:
            extractor_class = lookup_extractor(extractor_label)
            if extractor_class is None:
                raise ValueError(f"Extractor '{extractor_label}' not found")
        else:
            raise ValueError("Pipeline must specify an extractor")

        # Look up transformer (optional, defaults to IdentityTransformer)
        transformer_label = pipeline.get("transformer")
        if transformer_label:
            transformer_class = lookup_transformer(transformer_label)
            if transformer_class is None:
                raise ValueError(f"Transformer '{transformer_label}' not found")
        else:
            transformer_class = IdentityTransformer

        # Look up loader (optional, defaults to GenericLoader)
        loader_label = pipeline.get("loader")
        if loader_label:
            loader_class = lookup_loader(loader_label)
            if loader_class is None:
                raise ValueError(f"Loader '{loader_label}' not found")
        else:
            loader_class = GenericLoader

        return {
            "extractor": extractor_class,
            "transformer": transformer_class,
            "loader": loader_class,
        }

    elif site.get("scraper"):
        # Backward compatibility: wrap old-style fetcher
        fetcher = _get_old_style_fetcher(site)
        return FetcherAdapter(fetcher)

    else:
        raise ValueError("Site must have pipeline or scraper configured")


def _get_old_style_fetcher(site: dict[str, Any]):
    """Get an old-style fetcher for backward compatibility.

    Args:
        site: Site configuration dictionary.

    Returns:
        An instantiated fetcher object.
    """
    start_year = site["start_year"]
    try:
        start_year = datetime.datetime.strptime(
            site["last_updated"], "%Y-%m-%dT%H:%M:%S"
        ).year
    except (TypeError, ValueError):
        start_year = site["start_year"]

    fetcher_class = pm.hook.fetcher_class(label=site["scraper"])
    fetcher_class = [r for r in fetcher_class if r is not None]

    if fetcher_class:
        return fetcher_class[0](site, start_year, False)

    raise ValueError(f"Fetcher '{site['scraper']}' not found")
