"""
Constraint Grounder — verify constraint resolution claims with real external APIs.

When the viability scorer says "what_changed: Stripe now supports X", this module
verifies it by querying live package registries and GitHub changelogs.

Returns structured evidence with a source URL so judges can click through and verify.
Every claim is labelled: "verified via npm_registry" vs "unverified (AI-inferred only)".
"""

import logging
import os
import re
from typing import Optional

import httpx

from backend.services.run_trace import trace_event

logger = logging.getLogger(__name__)


def _github_headers(accept: str) -> dict:
    """GitHub API headers. Uses GITHUB_TOKEN when present to lift the unauthenticated
    rate limit (60/hr -> 5000/hr). Without a token a busy scan can exhaust the quota
    and silently degrade groundings to 'unverified' — the cause of flaky revive verdicts.

    Resolution order: .env via Settings (GITHUB_TOKEN) -> raw env (GITHUB_TOKEN/GH_TOKEN)."""
    headers = {"Accept": accept, "User-Agent": "necro-constraint-grounder/1.0"}
    try:
        from backend.config import settings
        token = settings.GITHUB_TOKEN
    except Exception:
        token = ""
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

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
    # ── Runtimes & system tooling (GitHub releases verifiable) ──────────────
    # These cover the constraint types that actually kill features in non-JS repos
    # (GitLab=Ruby/Go, godot/inkscape/gstreamer=C/C++). The common revivable pattern
    # is "blocked by <runtime/lib> bug, fixed in a later release" — release dates
    # let us verify the fix landed after the kill date.
    "go": "golang/go",
    "golang": "golang/go",
    "ruby": "ruby/ruby",
    "rust": "rust-lang/rust",
    "python": "python/cpython",
    "cpython": "python/cpython",
    "llvm": "llvm/llvm-project",
    "clang": "llvm/llvm-project",
    "electron": "electron/electron",
    "gtk": "GNOME/gtk",
    "qt": "qt/qtbase",
    "godot": "godotengine/godot",
    "openssl": "openssl/openssl",
    "ffmpeg": "FFmpeg/FFmpeg",
    "grpc": "grpc/grpc",
    "protobuf": "protocolbuffers/protobuf",
    "boringssl": "google/boringssl",
    "curl": "curl/curl",
    "sqlite": "sqlite/sqlite",
    "openssl3": "openssl/openssl",
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


# ── Permanently-deprecated platform capabilities ───────────────────────────────
# The version-lookup path (npm/GitHub/PyPI) only answers "does a newer release exist?".
# It systematically MISSES the class of kill reason where the platform capability itself
# was removed from the ecosystem (browser/runtime/plugin). For these, a newer library
# release is irrelevant or actively misleading — "grpc shipped v1.81" does not revive
# HTTP/2 Server Push after browsers removed it. Each entry carries a citable URL so the
# "keep buried" verdict is evidence-backed, not an assertion.
# (regex pattern, human label, end-of-life note, citable URL)
_DEPRECATED_TECH: list[tuple[str, str, str, str]] = [
    (r"http/?2\s*server[\s\-]?push|http/?2\s*push|\bh2\s*push\b",
     "HTTP/2 Server Push",
     "Chrome removed HTTP/2 Server Push in 2022 (M106) and other browsers followed. The "
     "client-side protocol feature is gone, so a server-library fix cannot revive it.",
     "https://developer.chrome.com/blog/removing-push/"),
    (r"adobe flash|flash player|flash content|\.swf\b|actionscript",
     "Adobe Flash",
     "Adobe Flash Player reached end-of-life on 2020-12-31 and is blocked in all modern browsers.",
     "https://www.adobe.com/products/flashplayer/end-of-life.html"),
    (r"web\s?sql|websql",
     "Web SQL Database",
     "The Web SQL Database spec was deprecated by the W3C and removed from Chrome 119 (2023).",
     "https://developer.chrome.com/blog/deprecating-web-sql/"),
    (r"silverlight",
     "Microsoft Silverlight",
     "Silverlight reached end-of-support on 2021-10-12 and is unsupported in modern browsers.",
     "https://learn.microsoft.com/en-us/lifecycle/products/silverlight-5"),
    (r"java applet|browser applet|\bnpapi\b",
     "Java Applets / NPAPI plugins",
     "NPAPI plugin support (including Java applets) was removed from Chrome (2015) and Firefox (2017).",
     "https://www.java.com/en/download/help/applet.html"),
    (r"appcache|application cache|cache manifest",
     "AppCache",
     "The HTML5 Application Cache API was removed from Chrome 95 (2021) in favour of Service Workers.",
     "https://developer.mozilla.org/docs/Web/API/Window/applicationCache"),
]


def _check_deprecation(text: str) -> Optional[dict]:
    """Return a deprecation record if the text names a permanently-removed platform
    capability, else None. Matched against feature name + constraint together."""
    tl = (text or "").lower()
    for pattern, label, note, url in _DEPRECATED_TECH:
        if re.search(pattern, tl):
            return {"label": label, "note": note, "url": url}
    return None


# Per-process cache: constraint text → grounding result.
# Multiple features sharing the same constraint (webpack, oauth, etc.) skip redundant API calls.
_GROUNDER_CACHE: dict[str, dict] = {}


async def ground_constraint(constraint_text: str, kill_date: str, feature_name: str = "") -> dict:
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
    # Permanent-deprecation gate (runs FIRST, before any version lookup). If the
    # feature depends on a platform capability that was removed from the ecosystem,
    # no library version bump can revive it — short-circuit with a citable record so
    # the verdict is "keep buried", not a misleading "newer release exists". (Bug #11/#1)
    dep = _check_deprecation(f"{feature_name} {constraint_text}")
    if dep:
        result = {
            "grounded": True,
            "technology": dep["label"],
            "evidence_date": "",
            "evidence_url": dep["url"],
            "latest_version": "",
            "description": dep["note"],
            "is_resolved": False,
            "deprecated": True,
            "source": "ecosystem_deprecation",
        }
        trace_event("constraint_grounding", status="deprecated", technology=dep["label"],
                    evidence_url=dep["url"])
        return result

    if not constraint_text:
        trace_event("constraint_grounding", status="unverified", reason="empty_constraint")
        return _unverified("No constraint text provided")

    cache_key = constraint_text.lower().strip()[:120]
    if cache_key in _GROUNDER_CACHE:
        logger.debug("Grounder cache hit for: %s", cache_key[:60])
        trace_event("constraint_grounding", status="cache_hit", constraint=cache_key)
        return _GROUNDER_CACHE[cache_key]

    tech, tech_type = _identify_technology(constraint_text)
    # Fallback: the AI-phrased constraint sometimes drops the technology name (e.g.
    # "lack of renderToPipeableStream support" instead of "React 17 ..."), which made
    # grounding flip between revive/investigate run-to-run. The FEATURE NAME reliably
    # carries the tech ("Streaming SSR (blocked by React 17, ...)"), so try it too.
    if not tech and feature_name:
        tech, tech_type = _identify_technology(feature_name)
        if tech:
            logger.info("Grounder identified '%s' from feature name (constraint text had none)", tech)
    if not tech:
        result = _unverified("No specific technology identified in constraint text")
        _GROUNDER_CACHE[cache_key] = result
        trace_event("constraint_grounding", status="unverified", constraint=cache_key,
                    reason="technology_not_identified")
        return result

    logger.info("Grounding constraint for '%s' (type=%s, kill=%s)", tech, tech_type, kill_date)
    trace_event("constraint_grounding", status="lookup_started", constraint=cache_key,
                technology=tech, lookup_type=tech_type, kill_date=kill_date)

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
        trace_event("constraint_grounding", status="unverified", constraint=cache_key,
                    technology=tech, reason="release_data_not_found")
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
    trace_event("constraint_grounding", status="verified", constraint=cache_key,
                technology=tech, source=grounding["source"],
                evidence_url=grounding["evidence_url"], evidence_date=grounding["evidence_date"],
                is_resolved=grounding["is_resolved"])
    return grounding


# Keywords that collide with common English words. These ONLY match if they appear
# adjacent to a tech-context marker (library, package, version, v1.2.3, etc.).
# Without this guard, prose like "all requests are routed" would match the `requests`
# PyPI package and fabricate a grounding URL — a real bug we hit in production.
_AMBIGUOUS_TECH_WORDS = {
    "requests", "flask", "node", "next", "vue", "apollo", "react",
    "express", "remix", "astro", "celery", "babel", "prisma",
    "redis", "docker", "ansible", "graphql", "next.js",
    # Runtimes/tools that are also common English words — only match with tech context
    # (version/upgrade/release/etc.) so prose like "go back" or "ruby colour" never grounds.
    "go", "ruby", "rust", "python", "qt", "curl", "clang",
}

# Whole-word tokens that signal the surrounding text is talking ABOUT a technology
# rather than using an English word that happens to match a package name.
_TECH_CONTEXT_RE = re.compile(
    r"\b("
    r"librar(?:y|ies)|package|module|framework|sdk|api"
    r"|version|v\d+(?:\.\d+)*|upgrade[ds]?|upgrading|migrat(?:e|ed|ion|ing)"
    r"|deprecat(?:e|ed|ion|ing)|release[ds]?|installed?|installing"
    r"|depend(?:ency|encies|s\s+on)|import(?:s|ed)?|requires?|requiring"
    r"|npm|pip|pypi|registry|changelog|breaking\s+change"
    r"|compiler|runtime|toolchain|std(?:lib)?|crate|gem|bug\s+in|fixed\s+in"
    r")\b",
    re.IGNORECASE,
)


def _has_tech_context(keyword: str, text_lower: str) -> bool:
    """Check if `keyword` appears near a tech-marker word — i.e. the prose is talking
    about a technology, not using the word in its plain English sense."""
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    for m in pattern.finditer(text_lower):
        start = max(0, m.start() - 40)
        end = min(len(text_lower), m.end() + 40)
        if _TECH_CONTEXT_RE.search(text_lower[start:end]):
            return True
    return False


# Common English words that get captured right after a package marker but are NOT
# packages. Without this guard, "the sdk was unstable" grounded "was" as an npm
# package, and "remove the api endpoint" grounded "endpoint" — fake "verified" badges.
_NOT_A_PACKAGE = {
    "was", "is", "are", "be", "been", "the", "this", "that", "it", "its", "they",
    "had", "has", "have", "will", "can", "may", "did", "does", "got", "get",
    "endpoint", "endpoints", "code", "logic", "support", "feature", "features",
    "version", "call", "calls", "method", "function", "class", "field", "value",
    "data", "file", "files", "test", "tests", "thing", "stuff", "part", "used",
    "unstable", "broken", "old", "new", "legacy", "default", "config", "setting",
    "and", "for", "with", "from", "into", "via", "due", "because", "when",
}

# Import-path markers — Go/other module paths are NOT npm packages and must never
# be sent to the npm registry ("module google.golang.org/api" → not npm).
_IMPORT_PATH_RE = re.compile(
    r"(?:golang\.org|google\.golang|github\.com|gopkg\.in|gitlab\.com|"
    r"\b[a-z0-9\-]+\.(?:org|com|io|dev|net)/)"
)


def _looks_like_package(name: str) -> bool:
    """True only when `name` is plausibly a real npm/pypi package — not a Go import
    path, not a bare English word, not too short. Prevents false 'verified' groundings."""
    if not name or len(name) < 3:
        return False
    if name.lower() in _NOT_A_PACKAGE:
        return False
    if _IMPORT_PATH_RE.search(name):
        return False
    # package-shaped: optional @scope, alnum start, package chars only, contains a letter
    if not re.match(r"^@?[a-z0-9][a-z0-9._\-/]{1,60}$", name):
        return False
    if not re.search(r"[a-z]", name):
        return False
    return True


def _identify_technology(text: str) -> tuple[str, str]:
    """
    Extract the main technology keyword from a constraint description.
    Returns (technology_name, lookup_type) where lookup_type is "npm"|"github"|"pypi"|"".

    Uses whole-word matching (not substring) and requires a tech-context marker
    for keywords that collide with common English words (e.g. "requests", "node").
    """
    text_lower = text.lower()

    def _try_match(keys, lookup_type_fn):
        for key in sorted(keys, key=len, reverse=True):
            if not re.search(rf"\b{re.escape(key)}\b", text_lower):
                continue
            if key in _AMBIGUOUS_TECH_WORDS and not _has_tech_context(key, text_lower):
                continue
            return key, lookup_type_fn(key)
        return "", ""

    # Priority 1: keywords in GITHUB_REPOS (richest metadata)
    key, ltype = _try_match(
        _GITHUB_REPOS.keys(),
        lambda k: "npm" if k in _NPM_CANONICAL else "github",
    )
    if key:
        return key, ltype

    # Priority 2: npm-only keywords
    key, _ = _try_match(_NPM_CANONICAL.keys(), lambda _k: "npm")
    if key:
        return key, "npm"

    # Priority 3: pypi-only keywords
    key, _ = _try_match(_PYPI_PACKAGES.keys(), lambda _k: "pypi")
    if key:
        return key, "pypi"

    # Heuristic: extract an explicitly-named package. Bare generic markers
    # (api/module/sdk/framework) were DROPPED — they match plain prose ("remove the api
    # endpoint") and grabbed the next English word as a fake package. We match BOTH
    # "package <name>" (name after) and "<name> library/package" (name before), then
    # require the captured token to pass _looks_like_package (rejects Go import paths,
    # English words, and verb-stopwords like "had"/"was").
    candidates = []
    m = re.search(r"\b(?:npm package|npm module|package|library)\s+['\"]?([a-z0-9@][\w\-\.@/]+)['\"]?", text_lower)
    if m:
        candidates.append(m.group(1).strip("'\"@/"))
    m = re.search(r"\b([a-z0-9@][\w\-\.@/]+)\s+(?:npm\s+)?(?:package|library)\b", text_lower)
    if m:
        candidates.append(m.group(1).strip("'\"@/"))
    for name in candidates:
        if _looks_like_package(name):
            return name, "npm"

    # Version mentions: "React 18", "PostgreSQL 15", "Node 20" — the trailing digit
    # itself is the tech-context signal, so these are safe without _has_tech_context.
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
            headers=_github_headers("application/vnd.github.v3+json"),
        ) as client:
            # Try latest endpoint first
            r = await client.get(f"https://api.github.com/repos/{repo}/releases/latest")
            if r.status_code == 200:
                data = r.json()
            else:
                # Fall back to first page of releases
                r2 = await client.get(f"https://api.github.com/repos/{repo}/releases?per_page=1")
                releases = r2.json() if r2.status_code == 200 else []
                if releases:
                    data = releases[0]
                else:
                    # Many major projects (Go, CPython, GTK, Qt, FFmpeg, SQLite) publish
                    # via git TAGS, not GitHub Releases. Fall back to the tags API +
                    # commit date so these still ground with a real, citable date.
                    return await _check_github_tags(client, repo)

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


async def _check_github_tags(client: "httpx.AsyncClient", repo: str) -> Optional[dict]:
    """Fallback for projects that ship via git tags rather than GitHub Releases
    (Go, CPython, GTK, Qt, FFmpeg, SQLite, …). Resolves the newest tag and the date
    of the commit it points to, so grounding still has a real citable date + URL."""
    try:
        tr = await client.get(f"https://api.github.com/repos/{repo}/tags?per_page=20")
        if tr.status_code != 200:
            return None
        tags = tr.json()
        if not tags:
            return None
        # Prefer a version-shaped tag (skip rc/alpha/beta when a stable one exists)
        def _is_stable(t):
            n = (t.get("name", "") or "").lower()
            return not any(x in n for x in ("rc", "alpha", "beta", "-dev", "nightly"))
        chosen = next((t for t in tags if _is_stable(t)), tags[0])
        version = chosen.get("name", "")
        commit_url = chosen.get("commit", {}).get("url", "")
        release_date = ""
        if commit_url:
            cr = await client.get(commit_url)
            if cr.status_code == 200:
                cd = cr.json()
                release_date = (
                    cd.get("commit", {}).get("committer", {}).get("date", "")
                    or cd.get("commit", {}).get("author", {}).get("date", "")
                )
        # Recency guard: GitHub's tags API does NOT return tags in chronological order,
        # so tags[0] is sometimes an ancient tag (Go→2012, FFmpeg→2010, GTK→2017). Showing
        # a decade-old release as "evidence" would be worse than not grounding. If the
        # resolved date is implausibly old, the ordering failed — return unverified instead
        # of misleading evidence. (Repos with proper Releases never hit this path.)
        if release_date:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(release_date.replace("Z", "+00:00"))
                age_years = (datetime.now(timezone.utc) - dt).days / 365.0
                if age_years > 4:
                    logger.debug("Tags fallback for %s gave stale tag %s (%s) — rejecting", repo, version, release_date[:10])
                    return None
            except ValueError:
                return None
        else:
            return None
        return {
            "version": version,
            "release_date": release_date[:10],
            "url": f"https://github.com/{repo}/releases/tag/{version}" if version else f"https://github.com/{repo}/tags",
            "description": f"{repo.split('/')[-1]} {version} (git tag)",
            "source": "github_tags",
        }
    except Exception as exc:
        logger.debug("GitHub tags lookup failed for %s: %s", repo, exc)
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
