import hashlib
import requests
import time
import argparse
import json
import os
import sys
from bs4 import BeautifulSoup

class ISOxError(Exception):
    """A failure ISOx understands well enough to explain in one line."""
    pass

def download_file(url, destination_path):
    part_path = destination_path + ".part"
    headers = {}
    existing = 0
    if os.path.exists(part_path):
        existing = os.path.getsize(part_path)
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

    response = requests.get(url, stream=True, timeout=20, headers=headers)

    if response.status_code == 416:
        os.remove(part_path)
        return download_file(url, destination_path)
    response.raise_for_status()

    if existing > 0 and response.status_code != 206:
        existing = 0
        mode = "wb"
    else:
        mode = "ab"

    if response.status_code == 206:
        content_range = response.headers.get("Content-Range")
        total = int(content_range.split("/")[-1]) if content_range else None
    else:
        content_length = response.headers.get("Content-Length")
        total = int(content_length) if content_length else None

    downloaded = existing
    start = time.time()
    bar_width = 30

    try:
        with open(part_path, mode) as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                elapsed = time.time() - start
                speed = (downloaded - existing) / elapsed if elapsed > 0 else 0
                if total:
                    filled = int(bar_width * downloaded / total)
                    bar = "#" * filled + "-" * (bar_width - filled)
                    percent = downloaded / total * 100
                    print(f"\r[{bar}] {percent:5.1f}%  {speed/1_000_000:6.2f} MB/s", end="", flush=True)
                else:
                    print(f"\rDownloaded {downloaded/1_000_000:.1f} MB  {speed/1_000_000:6.2f} MB/s", end="", flush=True)
    except OSError as e:
        print()
        raise OSError(f"Couldn't write to {part_path} ({e}). Check available disk space.") from e

    print()
    os.replace(part_path, destination_path)

def discover_via_html_listing(directory_url, required_substrings, must_end_with=".iso"):
    response = requests.get(directory_url, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    matches = [
        (link[2:] if link.startswith("./") else link)
        for link in links
        if link.endswith(must_end_with) and all(sub in link for sub in required_substrings)
    ]

    if not matches:
        raise ValueError(f"No matching filename found in directory listing (looking for {must_end_with})")
    return sorted(matches)[-1]

def find_latest_version_folder(directory_url, min_parts=1):
    response = requests.get(directory_url, timeout=10)
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

def is_unsafe_filename(filename):
    ## Reject filenames that could use escape characters
    return "/" in filename or "\\" in filename or ".." in filename

def compute_hash(filepath, algo):
    try:
        hasher = hashlib.new(algo)
    except ValueError:
        raise ValueError(f"Unsupported hash algorithm: '{algo}'. Check distros.json for a typo.")
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()

def verify_checksum(filepath, filename, hash_lookup, algo):
    if filename not in hash_lookup:
        raise ValueError(f"No checksum entry found for '{filename}' in the checksum file.")
    expected_hash = hash_lookup[filename]
    actual_hash = compute_hash(filepath, algo)
    return actual_hash == expected_hash

def check_mirror_throughput(url, sample_bytes=2_000_000):
    try:
        headers = {"Range": f"bytes=0-{sample_bytes - 1}"}
        start = time.time()
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()

        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded >= sample_bytes:
                break
        elapsed = time.time() - start
        speed = downloaded / elapsed
        return speed
    except requests.exceptions.RequestException:
        return None

def find_fastest_mirror_by_throughput(mirror_urls):
    results = {}
    for url in mirror_urls:
        speed = check_mirror_throughput(url)
        if speed is not None:
            results[url] = speed
            print(f"{url} sampled at {speed/1_000_000:.2f} MB/s")
        else:
            print(f"{url} is unreachable")

    if not results:
        raise ISOxError("none of the mirrors for this distro are reachable right now. "
                        "Try again soon, or swap the mirrors in distros.json.")
    fastest = max(results, key=results.get)
    return fastest


def run():
    try:
        with open("distros.json", "r") as f:
            distros = json.load(f)
    except FileNotFoundError as e:
        raise ISOxError("distros.json not found. The file is required to configure ISOx.") from e
    except json.JSONDecodeError as e:
        raise ISOxError("distros.json is malformed. Please check for typos in your configuration.") from e

    parser = argparse.ArgumentParser(description="Download and verify Linux ISOs")
    parser.add_argument("distro", nargs="?", choices=list(distros.keys()), help="Which distro to download")
    parser.add_argument("--list", action="store_true", help="List available distros and exit")
    args = parser.parse_args()          

    if args.list:
        print(f"{len(distros)} distros available:")
        for name in distros:
            print(f"  {name}")
        return

    if not args.distro:
        parser.error("a distro is required (or use --list to see options)")

    distro_info = distros[args.distro]
    required_keys = ["mirrors", "checksum_filename", "hash_algo"]
    missing = [k for k in required_keys if k not in distro_info]
    if missing:
        raise ISOxError(f"'{args.distro}' entry in distros.json is missing: {', '.join(missing)}")
    mirrors = distro_info["mirrors"]
    checksum_filename = distro_info["checksum_filename"]
    hash_algo = distro_info["hash_algo"]

    os.makedirs("ISOx_Downloads", exist_ok=True)

    ## For distros that have no stable/latest alias, the current version needs to be discovered before continuing
    ## This runs before ISO discovery, since HTML grabbing needs a complete path to get .iso
    if distro_info.get("version_directory", False):
        version_discovery_url = distro_info["version_discovery_url"]
        try:
            latest_version = find_latest_version_folder(version_discovery_url)
        except ValueError as e:
            raise ISOxError(f"couldn't find a version folder for '{args.distro}' at {version_discovery_url}") from e
        mirrors = [m.format(version=latest_version) for m in mirrors]
        print(f"Discovered latest version: {latest_version}")

    ## There are three ways to get ISO filenames, picked based on distros.json config fields
    # 1. "iso_filename" -> static and doesn't change, like Arch
    # 2. "iso_filename_contains" -> scan a shared checksum file
    # 3. "iso_filename_contains + html_scan" -> scan directory listing when no shared checksum is available
    if "iso_filename" in distro_info:
        iso_filename = distro_info["iso_filename"]
    else:
        required_substrings = distro_info["iso_filename_contains"]
        discovery_method = distro_info.get("discovery_method", "checksum_scan")

        if discovery_method == "html_scan":
            try:
                iso_filename = discover_via_html_listing(mirrors[0], required_substrings)
            except ValueError as e:
                raise ISOxError(f"couldn't find a matching ISO filename for '{args.distro}' in the directory listing.") from e
        else:
            peek_checksum_url = mirrors[0].rstrip("/") + "/" + checksum_filename
            response = requests.get(peek_checksum_url, timeout=10)
            response.raise_for_status()
            peek_lookup = {}
            for line in response.text.splitlines():
                parts = line.split()
                if len(parts) == 2:
                    peek_lookup[parts[1]] = parts[0]
            try:
                iso_filename = next(
                    f for f in peek_lookup
                    if all(sub in f for sub in required_substrings)
                )
            except StopIteration as e:
                raise ISOxError(f"couldn't find a matching ISO filename for '{args.distro}' in the checksum file.") from e

    ## If a filename looks suspicious, (../evil.iso type), reject it
    if is_unsafe_filename(iso_filename):
        raise ISOxError(f"discovered filename looks unsafe: '{iso_filename}'")

    iso_urls = [m.rstrip("/") + "/" + iso_filename for m in mirrors]
    best_iso_url = find_fastest_mirror_by_throughput(iso_urls)
    base = best_iso_url.rsplit("/", 1)[0]

    try:
        ## Checksum is either scraped, or built from a template using .format
        if distro_info.get("checksum_discovery_method") == "html_scan":
            try:
                checksum_filename_resolved = discover_via_html_listing(base, ["CHECKSUM"], must_end_with="CHECKSUM")
            except ValueError as e:
                raise ISOxError(f"couldn't find a checksum file for '{args.distro}' in the directory listing.") from e
        else:
            checksum_filename_resolved = checksum_filename.format(iso_filename=iso_filename)

        # Same case as previous
        if is_unsafe_filename(checksum_filename_resolved):
            raise ISOxError(f"discovered checksum filename looks unsafe: '{checksum_filename_resolved}'")

        checksum_url = f"{base}/{checksum_filename_resolved}"
        response = requests.get(checksum_url, timeout=10)
        response.raise_for_status()

        ## Some distributions publish their checksums in various ways. This handles that.
        # "single" - file is the hash
        # "bsd" - things like Fedora use this
        # "multi" - Default, i.e. <hash> <filename> type format
        checksum_format = distro_info.get("checksum_format", "multi")
        if checksum_format == "single":
            hash_lookup = {iso_filename: response.text.strip()}
        elif checksum_format == "bsd":
            hash_lookup = {}
            for line in response.text.splitlines():
                if line.upper().startswith(hash_algo.upper()) and "(" in line and ")" in line and "=" in line:
                    filename = line[line.index("(") + 1 : line.index(")")]
                    file_hash = line.split("=")[-1].strip()
                    hash_lookup[filename] = file_hash
        else:
            hash_lookup = {}
            for line in response.text.splitlines():
                parts = line.split()
                if len(parts) == 2:
                    filename = parts[1].lstrip("*")
                    hash_lookup[filename] = parts[0]

        destination_path = os.path.join("ISOx_Downloads", iso_filename)
        print(f"Downloading {iso_filename} from {base} ...")
        download_file(best_iso_url, destination_path)
    except requests.exceptions.RequestException as e:
        raise ISOxError(f"network request failed ({e}). Try running the script again.") from e

    try:
        if verify_checksum(destination_path, iso_filename, hash_lookup, hash_algo):
            print("Checksum matches, file is good.")
            return 
        quarantine = destination_path + ".FAILED"
        os.replace(destination_path, quarantine)
        print("WARNING: checksum mismatch, file may be corrupted or tampered with!")
        print(f"Renamed to {quarantine} so it can't be mistaken for a verified ISO.")
    except ValueError as e:
        quarantine = destination_path + ".UNVERIFIED"
        os.replace(destination_path, quarantine)
        print(f"Error: could not verify checksum ({e}). The ISO downloaded but was NOT verified.")
        print(f"Renamed to {quarantine}.")
    sys.exit(1)

def main():
    try:
        run()
    except ISOxError as e:
        print(f"Error: {e}")
        sys.exit(1)
    ## Safety Measures: for calls that didn't get a clean error message.
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