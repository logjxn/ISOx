import hashlib
import hmac
import requests
import time
import argparse
import json
import os
import site
import sys
import sysconfig
import re
from bs4 import BeautifulSoup

__version__ = "3.0.0"
PART_MAX_AGE_SECONDS = 24 * 60 * 60
DEFAULT_DOWNLOAD_DIR = "ISOx_Downloads"


def user_config_dir():
    """Per-user config directory, following the platform convention."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
    return os.path.join(
        base or os.path.join(os.path.expanduser("~"), ".config"), "isox"
    )


def distros_path_candidates():
    """Every place distros.json may live, most specific first.

    ISOX_DISTROS short-circuits the search so a typo'd path is reported rather
    than silently falling back to the bundled config.

    The install locations are plural because a wheel's data files land wherever
    the *install scheme* puts them, and the scheme varies by how pip was invoked.
    A venv or pipx install has sys.prefix and the data path coincide, but
    `pip install --user` puts them under the user base, and Debian's patched
    system Python defaults to /usr/local while sys.prefix stays /usr. Checking
    only sys.prefix means the tool cannot find its own config on either.
    """
    override = os.environ.get("ISOX_DISTROS")
    if override:
        return [override]
    candidates = [
        # A user's own copy wins, and unlike the bundled one it survives an
        # upgrade: pip replaces what it installed, so a customised mirror list
        # kept only there would silently revert on `pip install -U isox`.
        os.path.join(user_config_dir(), "distros.json"),
        # Beside the script: a git clone.
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "distros.json"),
        # The install scheme's own data directory: correct for Debian's
        # /usr/local default, and for anything else that relocates data.
        os.path.join(sysconfig.get_path("data"), "share", "isox", "distros.json"),
        # pip install --user.
        os.path.join(site.getuserbase(), "share", "isox", "distros.json"),
        # venv and pipx, where prefix and data coincide.
        os.path.join(sys.prefix, "share", "isox", "distros.json"),
    ]
    # These collapse to the same path on a normal install, and a "Looked in:"
    # list that repeats itself reads like a bug.
    return list(dict.fromkeys(candidates))


def resolve_distros_path():
    candidates = distros_path_candidates()
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[-1]


DISTROS_PATH = resolve_distros_path()

# Distros publish release candidates into the same directory as final releases
# (Alpine ships _rc1/_rc2 ISOs right beside the release they precede). "_" sorts
# above "-", so an RC beats the final of the same version in natural_sort_key and
# would be handed to the user as the current release. Always filtered; a distro
# can filter more via "iso_filename_excludes".
DEFAULT_FILENAME_EXCLUDES = ("_rc", "-rc", "_beta", "-beta", "_alpha", "-alpha")

USER_AGENT = f"ISOx/{__version__} (+https://github.com/logjxn/ISOx)"


def request_headers(extra=None):
    """Headers for every outbound request, identifying ISOx to mirror operators.

    requests defaults to "python-requests/x.y.z", which is indistinguishable from
    any other scraper and is exactly what rate-limit rules key on. Being nameable
    means an operator seeing unfamiliar traffic can look the project up, or
    allowlist it, rather than blanket-blocking an anonymous client. ISOx samples
    every mirror on every run, so it owes them that much.
    """
    headers = {"User-Agent": USER_AGENT}
    if extra:
        headers.update(extra)
    return headers


class ISOxError(Exception):
    """A failure ISOx understands well enough to explain in one line."""

    pass


def server_fingerprint(response):
    # Whatever the server gives to identify the version of the file given
    return response.headers.get("ETag") or response.headers.get("Last-Modified")


def read_meta(meta_path):
    """Return {"url": ..., "fingerprint": ...} for a .part, or None if unreadable."""
    try:
        with open(meta_path, "r") as f:
            raw = f.read().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except ValueError:
        stored = None
    # Pre-3.0 .meta files held a bare fingerprint. An ETag is a quoted string, so
    # json.loads() parses one happily: anything that isn't a dict is the old format,
    # and its raw text is the fingerprint.
    if not isinstance(stored, dict):
        return {"url": None, "fingerprint": raw}
    return {"url": stored.get("url"), "fingerprint": stored.get("fingerprint")}


def write_meta(meta_path, url, fingerprint):
    if fingerprint is None:
        return
    try:
        with open(meta_path, "w") as f:
            json.dump({"url": url, "fingerprint": fingerprint}, f)
    except OSError:
        pass  # Non-fatal: worst case scenario is a .part is discarded


def discard_part(part_path, meta_path):
    for path in (part_path, meta_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def part_is_stale(part_path, meta_path, url, fingerprint):
    # Distros with a fixed filename reuse the same name for new ISOs every month.
    # Appending June's bytes to July's files for example would corrupt the download.
    stored = read_meta(meta_path)
    # A fingerprint only means anything against the mirror that issued it. ETags are
    # per-server (nginx derives them from mtime+size, which differs per mirror), and
    # every run re-races the mirrors, so comparing one mirror's fingerprint against
    # another's would throw away a perfectly good .part whenever the race changes winner.
    if fingerprint is not None and stored is not None and stored["url"] == url:
        return stored["fingerprint"] != fingerprint
    # No fingerprint we can trust for this mirror, so age is the fallback estimate
    return (time.time() - os.path.getmtime(part_path)) > PART_MAX_AGE_SECONDS


def total_size_from(response):
    if response.status_code == 206:
        total = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else None
    length = response.headers.get("Content-Length")
    return int(length) if length and length.isdigit() else None


def version_discovery_urls(distro_info):
    """version_discovery_url accepts one URL or a list of them, tried in order."""
    configured = distro_info.get("version_discovery_url")
    if configured is None:
        return []
    if isinstance(configured, str):
        return [configured]
    return list(configured)


def excluded_substrings_for(distro_info):
    return DEFAULT_FILENAME_EXCLUDES + tuple(
        distro_info.get("iso_filename_excludes", ())
    )


def filename_matches(filename, required_substrings, excluded_substrings):
    return all(sub in filename for sub in required_substrings) and not any(
        bad in filename for bad in excluded_substrings
    )


def validate_distro_config(name, distro_info):
    missing = [
        k for k in ("mirrors", "checksum_filename", "hash_algo") if k not in distro_info
    ]
    if missing:
        raise ISOxError(
            f"'{name}' entry in distros.json is missing: {', '.join(missing)}"
        )
    if not distro_info["mirrors"]:
        raise ISOxError(
            f"'{name}' has an empty mirrors list. At least one mirror URL is required."
        )
    if distro_info.get("version_directory") and not version_discovery_urls(distro_info):
        raise ISOxError(
            f"'{name}' sets version_directory but has no version_discovery_url."
        )
    if "iso_filename" not in distro_info and "iso_filename_contains" not in distro_info:
        raise ISOxError(f"'{name}' needs either iso_filename or iso_filename_contains.")
    # Rejecting a bad algo here costs one function call. Letting it reach
    # verify_checksum costs a full multi-gigabyte download first, and then
    # quarantines the perfectly good ISO it just fetched.
    try:
        hashlib.new(distro_info["hash_algo"])
    except (ValueError, TypeError) as e:
        raise ISOxError(
            f"'{name}' uses a hash_algo Python doesn't support: "
            f"{distro_info['hash_algo']!r}"
        ) from e
    # A "single"-format checksum file is a bare hash with no filename in it,
    # so there is nothing for the scan to match against.
    if (
        "iso_filename" not in distro_info
        and distro_info.get("discovery_method", "checksum_scan") == "checksum_scan"
        and distro_info.get("checksum_format") == "single"
    ):
        raise ISOxError(
            f"'{name}' can't discover a filename by scanning a 'single'-format "
            f"checksum file, which lists no filenames."
        )
    # The checksum is the only trust anchor (no GPG), so a plain-HTTP URL
    # anywhere in the chain would let a MITM serve a matched ISO + hash.
    urls_needing_https = list(distro_info["mirrors"])
    urls_needing_https += version_discovery_urls(distro_info)
    if "checksum_base" in distro_info:
        urls_needing_https.append(distro_info["checksum_base"])
    for url in urls_needing_https:
        if not url.startswith("https://"):
            raise ISOxError(f"'{name}' contains a non-HTTPS URL: {url}")


def resolve_iso_filename(name, distro_info, sources, checksum_filename):
    # There are three ways to get ISO filenames, picked based on distros.json config fields
    # 1. "iso_filename" -> static and doesn't change, like Arch
    # 2. "iso_filename_contains" -> scan a shared checksum file
    # 3. "iso_filename_contains" + html_scan -> scan directory listing when no shared checksum exists
    if "iso_filename" in distro_info:
        return distro_info["iso_filename"]

    required_substrings = distro_info["iso_filename_contains"]
    excluded_substrings = excluded_substrings_for(distro_info)
    use_html_scan = distro_info.get("discovery_method", "checksum_scan") == "html_scan"

    # We don't want one dead source to kill discovery if the others are good.
    # Unreachable and no-match are treated the same, so we try sources in order until one works.
    for source in sources:
        try:
            if use_html_scan:
                return discover_via_html_listing(
                    source, required_substrings, excluded_substrings
                )
            peek_url = source.rstrip("/") + "/" + checksum_filename
            response = requests.get(peek_url, timeout=10, headers=request_headers())
            response.raise_for_status()
            peek_lookup = parse_checksum_file(
                response.text,
                distro_info.get("checksum_format", "multi"),
                distro_info["hash_algo"],
                None,
            )
            # A checksum file covers every artifact of a release, not just ISOs.
            # Kali's SHA256SUMS pairs each .iso with a .iso.torrent matching the
            # same substrings, so without the extension filter a 100KB torrent
            # can be downloaded, verified against its own hash, and reported good.
            candidates = [
                f
                for f in peek_lookup
                if f.endswith(".iso")
                and filename_matches(f, required_substrings, excluded_substrings)
            ]
            # Unlike a directory listing, a checksum file describes a single release,
            # so more than one match means the config is ambiguous rather than that
            # there are several versions to choose between. Guessing here is how you
            # ship debian-mac to someone who asked for debian, and it would verify
            # cleanly against its own published hash. Fail loudly instead.
            if len(candidates) > 1:
                raise ISOxError(
                    f"'{name}' matched {len(candidates)} ISOs in the checksum file at "
                    f"{peek_url}: {', '.join(sorted(candidates))}. Narrow "
                    f"iso_filename_contains or add iso_filename_excludes in distros.json."
                )
            if candidates:
                return candidates[0]
        except (requests.exceptions.RequestException, ValueError):
            pass
        print(f"Couldn't discover an ISO filename via {source}")

    raise ISOxError(
        f"couldn't discover an ISO filename for '{name}' from any of its "
        f"{len(sources)} sources."
    )


def resolve_checksum_filename(name, distro_info, base, checksum_filename, iso_filename):
    # Checksum is either scraped or built from a template (.format)
    if distro_info.get("checksum_discovery_method") == "html_scan":
        try:
            return discover_via_html_listing(
                base,
                [],
                excluded_substrings_for(distro_info),
                must_end_with="CHECKSUM",
            )
        except ValueError as e:
            raise ISOxError(
                f"couldn't find a checksum file for '{name}' in the directory listing at {base}."
            ) from e
    return checksum_filename.format(iso_filename=iso_filename)


def parse_checksum_file(text, checksum_format, hash_algo, iso_filename):
    # Some distributions publish their checksums in various ways. This handles that.
    # "single" - file is the hash
    # "bsd" - things like Fedora use this
    # "multi" - Default, i.e. <hash> <filename> type format
    if checksum_format == "single":
        return {iso_filename: text.strip()}

    hash_lookup = {}
    if checksum_format == "bsd":
        for line in text.splitlines():
            if (
                line.upper().startswith(hash_algo.upper())
                and "(" in line
                and ")" in line
                and "=" in line
            ):
                filename = line[line.index("(") + 1 : line.index(")")]
                hash_lookup[filename] = line.split("=")[-1].strip()
    else:
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2:
                hash_lookup[parts[1].lstrip("*")] = parts[0]
    return hash_lookup


def download_file(url, destination_path):
    part_path = destination_path + ".part"
    meta_path = part_path + ".meta"

    existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    headers = request_headers({"Range": f"bytes={existing}-"} if existing > 0 else None)

    try:
        response = requests.get(url, stream=True, timeout=20, headers=headers)

        # .part is bigger than server's file, causing issues
        if response.status_code == 416:
            response.close()
            discard_part(part_path, meta_path)
            return download_file(url, destination_path)

        response.raise_for_status()
        fingerprint = server_fingerprint(response)

        if (
            existing > 0
            and response.status_code == 206
            and part_is_stale(part_path, meta_path, url, fingerprint)
        ):
            response.close()
            print("Partial download doesn't match file on server. Starting fresh.")
            discard_part(part_path, meta_path)
            return download_file(url, destination_path)

        if existing > 0 and response.status_code != 206:
            existing = 0  # Server ignored Range header, so start over
            mode = "wb"  # Starts file from 0
        else:
            mode = "ab"  # Appends bytes to end

        if existing > 0:
            print(f"Resuming from {existing / 1_000_000:.1f} MB ...")

        total = total_size_from(response)
        write_meta(meta_path, url, fingerprint)

        downloaded = existing
        start = time.time()
        bar_width = 30

        with open(part_path, mode) as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                elapsed = time.time() - start
                speed = (downloaded - existing) / elapsed if elapsed > 0 else 0
                if total:
                    fraction = min(downloaded / total, 1.0)
                    filled = int(bar_width * fraction)
                    bar = "#" * filled + "-" * (bar_width - filled)
                    print(
                        f"\r[{bar}] {fraction * 100:5.1f}%  {speed / 1_000_000:6.2f} MB/s",
                        end="",
                        flush=True,
                    )
                else:
                    print(
                        f"\rDownloaded {downloaded / 1_000_000:.1f} MB  {speed / 1_000_000:6.2f} MB/s",
                        end="",
                        flush=True,
                    )
    # RequestException subclasses OSError, so it must be caught first.
    # or, the handler below would eat every network failure and say it's a disk error.
    except requests.exceptions.RequestException as e:
        print()
        raise ISOxError(
            f"download failed ({e}). Re-run to resume from where it stopped."
        ) from e
    except OSError as e:
        print()
        raise ISOxError(
            f"Couldn't write to {part_path} ({e}). Check available disk space."
        ) from e

    print()
    # Promoting a short read would turn a resumable .part into a .FAILED ISO:
    # the bytes on disk are fine, there are just fewer of them than promised.
    if total is not None and downloaded != total:
        raise ISOxError(
            f"download ended early ({downloaded} of {total} bytes). "
            f"Re-run to resume from where it stopped."
        )
    os.replace(part_path, destination_path)
    discard_part(part_path, meta_path)


def natural_sort_key(name):
    # "foo-10.iso" -> ["foo-", 10, ".iso"], so 10 outranks 9 instead of losing
    # to it lexicographically. re.split with a capturing group alternates
    # text/digits, so two keys never compare int against str at the same index.
    return [
        int(part) if part.isdecimal() else part for part in re.split(r"(\d+)", name)
    ]


def discover_via_html_listing(
    directory_url, required_substrings, excluded_substrings=(), must_end_with=".iso"
):
    response = requests.get(directory_url, timeout=10, headers=request_headers())
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    matches = [
        (link[2:] if link.startswith("./") else link)
        for link in links
        if link.endswith(must_end_with)
        and filename_matches(link, required_substrings, excluded_substrings)
    ]

    if not matches:
        raise ValueError(
            f"No matching filename found in directory listing (looking for {must_end_with})"
        )
    return max(matches, key=natural_sort_key)


def find_latest_version_folder(directory_url, min_parts=1):
    response = requests.get(directory_url, timeout=10, headers=request_headers())
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]

    version_folders = []
    for link in links:
        cleaned = link.rstrip("/")
        parts = cleaned.split(".")
        if all(part.isdigit() for part in parts) and len(parts) >= min_parts:
            version_folders.append((tuple(int(p) for p in parts), cleaned))

    if not version_folders:
        raise ValueError("No version-numbered folders found in directory listing")

    version_folders.sort(key=lambda x: x[0])
    return version_folders[-1][1]


def find_latest_lts_folder(directory_url):
    # Ubuntu LTS releases are always "YY.04" with YY even; this also
    # skips dated snapshot folders like "24.04.2" in favor of the
    # "24.04" alias, which Canonical keeps updated with the latest ISO.
    response = requests.get(directory_url, timeout=10, headers=request_headers())
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]

    lts_folders = []
    for link in links:
        cleaned = link.rstrip("/")
        parts = cleaned.split(".")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            year, month = int(parts[0]), int(parts[1])
            if month == 4 and year % 2 == 0:
                lts_folders.append((year, cleaned))

    if not lts_folders:
        raise ValueError("No LTS-style (YY.04) folders found in directory listing")

    lts_folders.sort()
    return lts_folders[-1][1]


def find_latest_version(name, discovery_urls, finder):
    # Version discovery decides which directory everything else is fetched from,
    # so a single unreachable host here used to fail the whole run even when every
    # configured mirror was healthy. Same fallback shape as ISO discovery.
    for url in discovery_urls:
        try:
            return finder(url)
        except (requests.exceptions.RequestException, ValueError):
            print(f"Couldn't discover a version via {url}")
    raise ISOxError(
        f"couldn't find a version folder for '{name}' from any of its "
        f"{len(discovery_urls)} version_discovery_url entries."
    )


def is_unsafe_filename(filename):
    # Reject filenames that could use escape characters
    return "/" in filename or "\\" in filename or ".." in filename


def compute_hash(filepath, algo):
    try:
        hasher = hashlib.new(algo)
    except ValueError as e:
        raise ValueError(
            f"Unsupported hash algorithm: '{algo}'. Check distros.json for a typo."
        ) from e
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_checksum(filepath, filename, hash_lookup, algo):
    if filename not in hash_lookup:
        raise ValueError(
            f"No checksum entry found for '{filename}' in the checksum file."
        )
    # hexdigest() is always lowercase but published hashes aren't consistently so,
    # and a case difference here would be reported as "may be tampered with".
    expected_hash = hash_lookup[filename].strip().lower()
    actual_hash = compute_hash(filepath, algo).lower()
    return hmac.compare_digest(actual_hash.encode(), expected_hash.encode())


def quarantine_download(destination_path, suffix):
    """Rename a file that failed verification so it can't pass for a good ISO."""
    quarantine_path = destination_path + suffix
    os.replace(destination_path, quarantine_path)
    return quarantine_path


def check_mirror_throughput(url, sample_bytes=2_000_000):
    try:
        headers = request_headers({"Range": f"bytes=0-{sample_bytes - 1}"})
        start = time.time()
        # Closed explicitly: we stop reading at the sample size, so the connection
        # would otherwise sit unreleased until GC, and a mirror that ignored Range
        # would go on pushing the whole ISO into the socket meanwhile.
        with requests.get(url, headers=headers, stream=True, timeout=10) as response:
            response.raise_for_status()

            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded >= sample_bytes:
                    break
            elapsed = max(time.time() - start, 1e-6)  # Clock granularity can report 0
        return downloaded / elapsed
    except requests.exceptions.RequestException:
        return None


def find_fastest_mirror_by_throughput(mirror_urls):
    results = {}
    for url in mirror_urls:
        speed = check_mirror_throughput(url)
        if speed is not None:
            results[url] = speed
            print(f"{url} sampled at {speed / 1_000_000:.2f} MB/s")
        else:
            print(f"{url} is unreachable")

    if not results:
        raise ISOxError(
            "none of the mirrors for this distro are reachable right now. "
            "Try again soon, or swap the mirrors in distros.json."
        )
    fastest = max(results, key=results.get)
    return fastest


def run():
    try:
        with open(DISTROS_PATH, "r") as f:
            distros = json.load(f)
    except FileNotFoundError as e:
        searched = "\n  ".join(distros_path_candidates())
        raise ISOxError(
            f"distros.json not found. The file is required to configure ISOx.\n"
            f"Looked in:\n  {searched}\n"
            f"Set ISOX_DISTROS to point at your own copy."
        ) from e
    except json.JSONDecodeError as e:
        raise ISOxError(
            "distros.json is malformed. Please check for typos in your configuration."
        ) from e

    parser = argparse.ArgumentParser(description="Download and verify Linux ISOs")
    parser.add_argument(
        "distro",
        nargs="?",
        choices=list(distros.keys()),
        help="Which distro to download",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available distros and exit"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help=f"Where to save the ISO (default: ./{DEFAULT_DOWNLOAD_DIR})",
    )
    parser.add_argument("--version", action="version", version=f"ISOx {__version__}")
    args = parser.parse_args()

    if args.list:
        print(f"{len(distros)} distros available:")
        for name in distros:
            print(f"  {name}")
        # Which config won matters once there's more than one place it can live.
        print(f"\nconfig: {DISTROS_PATH}")
        return

    if not args.distro:
        parser.error("a distro is required (or use --list to see options)")

    distro_info = distros[args.distro]
    validate_distro_config(args.distro, distro_info)

    mirrors = distro_info["mirrors"]
    checksum_filename = distro_info["checksum_filename"]
    hash_algo = distro_info["hash_algo"]
    checksum_base = distro_info.get("checksum_base")

    os.makedirs(args.output_dir, exist_ok=True)

    # For distros that have no stable/latest alias, the current version needs to be discovered before continuing
    # This runs before ISO discovery, since HTML grabbing needs a complete path to get .iso
    if distro_info.get("version_directory", False):
        finder = (
            find_latest_lts_folder
            if distro_info.get("version_scheme") == "ubuntu_lts"
            else find_latest_version_folder
        )
        latest_version = find_latest_version(
            args.distro, version_discovery_urls(distro_info), finder
        )
        mirrors = [m.format(version=latest_version) for m in mirrors]
        if checksum_base:
            checksum_base = checksum_base.format(version=latest_version)
        print(f"Discovered latest version: {latest_version}")

    # When a canonical host is configured it also decides the filename. Taking the
    # name from one host and the hash from another quarantines a perfectly good ISO
    # every time a mirror lags a release behind.
    discovery_sources = ([checksum_base] if checksum_base else []) + mirrors

    iso_filename = resolve_iso_filename(
        args.distro, distro_info, discovery_sources, checksum_filename
    )

    # If a filename looks suspicious, (../evil.iso type), reject it
    if is_unsafe_filename(iso_filename):
        raise ISOxError(f"discovered filename looks unsafe: '{iso_filename}'")

    iso_urls = [m.rstrip("/") + "/" + iso_filename for m in mirrors]
    best_iso_url = find_fastest_mirror_by_throughput(iso_urls)
    base = best_iso_url.rsplit("/", 1)[0]

    # A mirror that serves a modified ISO can serve a hash that matches it just as
    # easily, which makes verification against that same mirror worth very little.
    # Pulling the checksum from the distro's own host means one rogue mirror can't
    # supply both halves.
    checksum_source = checksum_base.rstrip("/") if checksum_base else base

    checksum_filename_resolved = resolve_checksum_filename(
        args.distro, distro_info, checksum_source, checksum_filename, iso_filename
    )

    if is_unsafe_filename(checksum_filename_resolved):
        raise ISOxError(
            f"discovered checksum filename looks unsafe: '{checksum_filename_resolved}'"
        )

    checksum_url = f"{checksum_source}/{checksum_filename_resolved}"
    try:
        response = requests.get(checksum_url, timeout=10, headers=request_headers())
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise ISOxError(
            f"couldn't fetch the checksum for '{args.distro}' from {checksum_url} ({e}). "
            f"Without it the ISO can't be verified, so nothing was downloaded."
        ) from e
    hash_lookup = parse_checksum_file(
        response.text,
        distro_info.get("checksum_format", "multi"),
        hash_algo,
        iso_filename,
    )

    destination_path = os.path.join(args.output_dir, iso_filename)
    print(f"Downloading {iso_filename} from {base} ...")
    if checksum_source != base:
        print(f"Verifying against the checksum published at {checksum_source} ...")
    download_file(best_iso_url, destination_path)

    # Stays a local handler since it has the purpose of quarantining, and is not needed elsewhere.
    try:
        if verify_checksum(destination_path, iso_filename, hash_lookup, hash_algo):
            print("Checksum matches, file is good.")
            return
        quarantine = quarantine_download(destination_path, ".FAILED")
        print("WARNING: checksum mismatch, file may be corrupted or tampered with!")
        print(f"Renamed to {quarantine} so it can't be mistaken for a verified ISO.")
    except ValueError as e:
        quarantine = quarantine_download(destination_path, ".UNVERIFIED")
        print(
            f"Error: could not verify checksum ({e}). The ISO downloaded but was NOT verified."
        )
        print(f"Renamed to {quarantine}.")
    sys.exit(1)


def main():
    try:
        run()
    except ISOxError as e:
        print(f"Error: {e}")
        sys.exit(1)
    # Safety Measures: for calls that didn't get a clean error message.
    except requests.exceptions.RequestException as e:
        print(f"Error: network request failed ({e}). Try running the tool again.")
        sys.exit(1)
    except OSError as e:
        print(f"Error: filesystem operation failed ({e}).")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted. Any partial download was kept, re-run to resume.")
        sys.exit(130)


if __name__ == "__main__":
    main()
