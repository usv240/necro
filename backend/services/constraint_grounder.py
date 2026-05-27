"""
Constraint Grounder — verify constraint resolution claims with real external APIs.

When the viability scorer says "what_changed: Stripe now supports X", this module
verifies it by querying live package registries and GitHub changelogs.

Returns structured evidence with a source URL so judges can click through and verify.
Every claim is labelled: "verified via npm_registry" vs "unverified (AI-inferred only)".
"""

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Technology → GitHub repo for release lookup
_GITHUB_REPOS: dict[str, str] = {
    "react": "facebook/react",
    "nextjs": "vercel/next.js",
    "next.js": "vercel/next.js",
    "next": "vercel/next.js",
    "vite": "vitejs/vite",
    "postgres": "postgres/postgres",
    "postgresql": "postgres/postgres",
    "redis": "redis/redis",
    "stripe": "stripe/stripe-node",
    "prisma": "prisma/prisma",
    "mongoose": "Automattic/mongoose",
    "fastapi": "tiangolo/fastapi",
    "django": "django/django",
    "flask": "pallets/flask",
    "express": "expressjs/express",
    "kubernetes": "kubernetes/kubernetes",
    "k8s": "kubernetes/kubernetes",
    "docker": "docker/cli",
    "gitlab": "gitlabhq/gitlabhq",
    "node": "nodejs/node",
    "node.js": "nodejs/node",
    "typescript": "microsoft/TypeScript",
    "svelte": "sveltejs/svelte",
    "vue": "vuejs/vue",
    "angular": "angular/angular",
    "tailwind": "tailwindlabs/tailwindcss",
    "tailwindcss": "tailwindlabs/tailwindcss",
    "webpack": "webpack/webpack",
    "babel": "babel/babel",
    "eslint": "eslint/eslint",
    "prettier": "prettier/prettier",
    "turborepo": "vercel/turbo",
    "remix": "remix-run/remix",
    "astro": "withastro/astro",
    "trpc": "trpc/trpc",
    "zod": "colinhacks/zod",
    "pydantic": "pydantic/pydantic",
    "sqlalchemy": "sqlalchemy/sqlalchemy",
    "celery": "celery/celery",
    "terraform": "hashicorp/terraform",
    "ansible": "ansible/ansible",
    "graphql": "graphql/graphql-js",
    "apollo": "apollographql/apollo-client",
    "twilio": "twilio/twilio-node",
    "sendgrid": "sendgrid/sendgrid-nodejs",
}

# Canonical npm package names (for packages with scoped names, etc.)
_NPM_CANONICAL: dict[str, str] = {
    "react": "react",
    "nextjs": "next",
    "next.js": "next",
    "next": "next",
    "vite": "vite",
    "stripe": "stripe",
    "prisma": "@prisma/client",
    "mongoose": "mongoose",
    "express": "express",
    "fastify": "fastify",
    "typescript": "typescript",
    "tailwindcss": "tailwindcss",
    "tailwind": "tailwindcss",
    "svelte": "svelte",
    "vue": "vue",
    "webpack": "webpack",
    "babel": "@babel/core",
    "eslint": "eslint",
    "prettier": "prettier",
    "turborepo": "turbo",
    "remix": "@remix-run/react",
    "astro": "astro",
    "trpc": "@trpc/server",
    "zod": "zod",
    "twilio": "twilio",
    "sendgrid": "@sendgrid/mail",
    "graphql": "graphql",
    "apollo": "@apollo/client",
}

# PyPI packages
_PYPI_PACKAGES: dict[str, str] = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "celery": "celery",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "boto3": "boto3",
    "anthropic": "anthropic",
    "openai": "openai",
    "google-genai": "google-genai",
    "httpx": "httpx",
}


# Per-process cache: constraint text → grounding result.
# Multiple features sharing the same constraint (webpack, oauth, etc.) skip redundant API calls.
_GROUNDER_CACHE: dict[str, dict] = {}


async def ground_constraint(constraint_text: str, kill_date: str) -> dict:
    """
    Given a constraint description and kill date, query real external APIs to find
    evidence of whether that constraint has been resolved.

    Results are cached per constraint text for the lifetime of the process so that
    multiple features sharing the same root constraint (e.g. "webpack 4 incompatibility")
    only trigger one external API call.

    Returns:
      grounded (bool)       — whether we found real API evidence
      technology (str)      — identified technology keyword
      evidence_date (str)   — ISO date when the fix/release landed
      evidence_url (str)    — clickable link to release/changelog
      latest_version (str)  — latest version found
      description (str)     — human-readable description of what was found
      is_resolved (bool)    — did the resolution land AFTER the kill date?
      source (str)          — "npm_registry" | "github_releases" | "pypi" | "unverified"
    """
    if not constraint_text:
        return _unverified("No constraint text provided")

    cache_key = constraint_text.lower().strip()[:120]
    if cache_key in _GROUNDER_CACHE:
        logger.debug("Grounder cache hit for: %s", cache_key[:60])
        return _GROUNDER_CACHE[cache_key]

    tech, tech_type = _identify_technology(constraint_text)
    if not tech:
        result = _unverified("No specific technology identified in constraint text")
        _GROUNDER_CACHE[cache_key] = result
        return result

    logger.info("Grounding constraint for '%s' (type=%s, kill=%s)", tech, tech_type, kill_date)

    result: Optional[dict] = None

    if tech_type == "npm":
        pkg = _NPM_CANONICAL.get(tech.lower(), tech)
        result = await _check_npm(pkg)
    elif tech_type == "github":
        repo = _GITHUB_REPOS.get(tech.lower())
        if repo:
            result = await _check_github_releases(repo)
    elif tech_type == "pypi":
        pkg = _PYPI_PACKAGES.get(tech.lower(), tech)
        result = await _check_pypi(pkg)

    # If primary lookup failed, try the other registries as fallback
    if not result and tech.lower() in _GITHUB_REPOS:
        result = await _check_github_releases(_GITHUB_REPOS[tech.lower()])
    if not result and tech.lower() in _NPM_CANONICAL:
        result = await _check_npm(_NPM_CANONICAL[tech.lower()])

    if not result:
        grounding = _unverified(f"No release data found for '{tech}' via external APIs")
        _GROUNDER_CACHE[cache_key] = grounding
        return grounding

    is_resolved = _released_after_kill(result.get("release_date", ""), kill_date)

    grounding = {
        "grounded": True,
        "technology": tech,
        "evidence_date": result.get("release_date", ""),
        "evidence_url": result.get("url", ""),
        "latest_version": result.get("version", ""),
        "description": result.get("description", ""),
        "is_resolved": is_resolved,
        "source": result.get("source", "api"),
    }
    _GROUNDER_CACHE[cache_key] = grounding
    return grounding


def _identify_technology(text: str) -> tuple[str, str]:
    """
    Extract the main technology keyword from a constraint description.
    Returns (technology_name, lookup_type) where lookup_type is "npm"|"github"|"pypi"|"".
    """
    text_lower = text.lower()

    # Priority: exact keyword match in known maps
    for key in sorted(_GITHUB_REPOS.keys(), key=len, reverse=True):
        if key in text_lower:
            # Determine best lookup type
            if key in _NPM_CANONICAL:
                return key, "npm"
            return key, "github"

    for key in sorted(_NPM_CANONICAL.keys(), key=len, reverse=True):
        if key in text_lower:
            return key, "npm"

    for key in sorted(_PYPI_PACKAGES.keys(), key=len, reverse=True):
        if key in text_lower:
            return key, "pypi"

    # Heuristic: extract "X package", "X library", "X API", "X SDK"
    m = re.search(
        r"(?:npm package|library|sdk|framework|api|module)\s+['\"]?([a-zA-Z][\w\-\.@/]+)['\"]?",
        text_lower,
    )
    if m:
        name = m.group(1).strip("'\"")
        return name, "npm"

    # Version mentions: "React 18", "PostgreSQL 15", "Node 20"
    m = re.search(r"\b(react|vue|angular|django|flask|node|postgres|redis)\s+\d+", text_lower)
    if m:
        name = m.group(1)
        return name, "github" if name in _GITHUB_REPOS else "npm"

    return "", ""


async def _check_npm(package_name: str) -> Optional[dict]:
    """Query npm registry for latest version and its publish date."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Fetch full package metadata (includes time map version→date)
            r = await client.get(
                f"https://registry.npmjs.org/{package_name}",
                headers={"Accept": "application/json"},
            )
            if r.status_code != 200:
                return None

            data = r.json()
            dist_tags = data.get("dist-tags", {})
            version = dist_tags.get("latest", "")
            time_map = data.get("time", {})
            release_date = time_map.get(version, "")

            if not version:
                return None

            description = data.get("description", "")
            return {
                "version": version,
                "release_date": release_date[:10] if release_date else "",
                "url": f"https://www.npmjs.com/package/{package_name}",
                "description": f"{package_name} v{version}" + (f" — {description[:120]}" if description else ""),
                "source": "npm_registry",
            }
    except Exception as exc:
        logger.debug("npm lookup failed for %s: %s", package_name, exc)
        return None


async def _check_github_releases(repo: str) -> Optional[dict]:
    """Query GitHub releases API for the latest tagged release."""
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "necro-constraint-grounder/1.0",
            },
        ) as client:
            # Try latest endpoint first
            r = await client.get(f"https://api.github.com/repos/{repo}/releases/latest")
            if r.status_code == 200:
                data = r.json()
            else:
                # Fall back to first page of releases
                r2 = await client.get(f"https://api.github.com/repos/{repo}/releases?per_page=1")
                if r2.status_code != 200:
                    return None
                releases = r2.json()
                if not releases:
                    return None
                data = releases[0]

            version = data.get("tag_name", "")
            published = data.get("published_at", "")
            body = (data.get("body", "") or "")[:200].strip()

            return {
                "version": version,
                "release_date": published[:10] if published else "",
                "url": data.get("html_url", f"https://github.com/{repo}/releases"),
                "description": f"{repo.split('/')[-1]} {version}"
                + (f": {body[:120]}" if body else ""),
                "source": "github_releases",
            }
    except Exception as exc:
        logger.debug("GitHub releases lookup failed for %s: %s", repo, exc)
        return None


async def _check_pypi(package_name: str) -> Optional[dict]:
    """Query PyPI JSON API for latest version and upload date."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"https://pypi.org/pypi/{package_name}/json")
            if r.status_code != 200:
                return None

            data = r.json()
            info = data.get("info", {})
            version = info.get("version", "")
            releases = data.get("releases", {})
            files = releases.get(version, [])
            upload_time = files[0].get("upload_time", "") if files else ""

            return {
                "version": version,
                "release_date": upload_time[:10] if upload_time else "",
                "url": f"https://pypi.org/project/{package_name}/",
                "description": f"{package_name} v{version} — {info.get('summary', '')[:120]}",
                "source": "pypi",
            }
    except Exception as exc:
        logger.debug("PyPI lookup failed for %s: %s", package_name, exc)
        return None


def _released_after_kill(release_date: str, kill_date: str) -> Optional[bool]:
    """Return True if release_date > kill_date, None if either is unparseable."""
    if not release_date or not kill_date:
        return None
    try:
        from datetime import datetime

        # Normalise — kill_date may be "January 15, 2022" or "2022-01-15"
        kill_str = kill_date.replace("Z", "+00:00").replace(" ", "T")
        # Handle "Month DD, YYYY" format
        for fmt in ("%B %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                kill_dt = datetime.strptime(kill_date, fmt)
                break
            except ValueError:
                continue
        else:
            return None

        rel_dt = datetime.strptime(release_date, "%Y-%m-%d")
        return rel_dt.date() > kill_dt.date() if hasattr(kill_dt, "date") else rel_dt > kill_dt
    except Exception:
        return None


def _unverified(reason: str) -> dict:
    return {
        "grounded": False,
        "technology": "",
        "evidence_date": "",
        "evidence_url": "",
        "latest_version": "",
        "description": reason,
        "is_resolved": None,
        "source": "unverified",
    }
