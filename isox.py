import hashlib
import requests
import time
import argparse
import json
import os
from bs4 import BeautifulSoup

def download_file(url, destination_path):
    response = requests.get(url, stream=True, timeout=10)
    response.raise_for_status()
    with open(destination_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

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
        raise Exception("No reachable mirrors")
    fastest = max(results, key=results.get)
    return fastest


def main():
    with open("distros.json", "r") as f:
        distros = json.load(f)

    parser = argparse.ArgumentParser(description="Download and verify Linux ISOs")
    parser.add_argument("distro", choices=list(distros.keys()), help="Which distro to download")
    args = parser.parse_args()
    distro_info = distros[args.distro]
    required_keys = ["mirrors", "checksum_filename", "hash_algo"]
    missing = [k for k in required_keys if k not in distro_info]
    if missing:
        print(f"Error: '{args.distro}' entry in distros.json is missing: {', '.join(missing)}")
        return
    mirrors = distro_info["mirrors"]
    checksum_filename = distro_info["checksum_filename"]
    hash_algo = distro_info["hash_algo"]

    os.makedirs("ISOx_Downloads", exist_ok=True)

    ## For distros that have no stable/latest alias, th current version needs to be discovered before continuing
    ## This runs before ISO discovery, since HTML grabbing needs a complete path to get .iso
    if distro_info.get("version_directory", False):
        version_discovery_url = distro_info["version_discovery_url"]
        try:
            latest_version = find_latest_version_folder(version_discovery_url)
        except ValueError:
            print(f"Error: couldn't find a version folder for '{args.distro}' at {version_discovery_url}")
            return
        mirrors = [m.format(version=latest_version) for m in mirrors]
        print(f"Discovered latest version: {latest_version}")

    ## There are three ways to get ISO filenames, picked based on distros.json config fields
    # 1. "iso_filename" -> static and doesn't change, like Arch
    # 2. "iso_filename_contains" -> scan a shared checksum file
    # 3. "iso_filename_contains + html_scan" -> scan directory lising when no shared checksum is available
    if "iso_filename" in distro_info:
        iso_filename = distro_info["iso_filename"]
    else:
        required_substrings = distro_info["iso_filename_contains"]
        discovery_method = distro_info.get("discovery_method", "checksum_scan")

        if discovery_method == "html_scan":
            try:
                iso_filename = discover_via_html_listing(mirrors[0], required_substrings)
            except ValueError:
                print(f"Error: couldn't find a matching ISO filename for '{args.distro}' in the directory listing.")
                return
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
            except StopIteration:
                print(f"Error: couldn't find a matching ISO filename for '{args.distro}' in the checksum file.")
                return
    ## If a filename feels suspicious/has malicious characters, (../evil.iso type), reject it
    if is_unsafe_filename(iso_filename):
        print(f"Error: discovered filename looks unsafe: '{iso_filename}'")
        return

    iso_urls = [m.rstrip("/") + "/" + iso_filename for m in mirrors]
    best_iso_url = find_fastest_mirror_by_throughput(iso_urls)
    base = best_iso_url.rsplit("/", 1)[0]

    try:
        ## Checksum is either scraped, or built from a template using .format
        if distro_info.get("checksum_discovery_method") == "html_scan":
            try:
                checksum_filename_resolved = discover_via_html_listing(base, ["CHECKSUM"], must_end_with="CHECKSUM")
            except ValueError:
                print(f"Error: couldn't find a checksum file for '{args.distro}' in the directory listing.")
                return
        else:
            checksum_filename_resolved = checksum_filename.format(iso_filename=iso_filename)

        # Same case as previous
        if is_unsafe_filename(checksum_filename_resolved):
            print(f"Error: discovered checksum filename looks unsafe: '{checksum_filename_resolved}'")
            return

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
        print(f"Error: network request failed ({e}). Try running the script again.")
        return

    if verify_checksum(destination_path, iso_filename, hash_lookup, hash_algo):
        print("Checksum matches, file is good.")
    else:
        print("WARNING: checksum mismatch, file may be corrupted or tampered with!")

if __name__ == "__main__":
    main()
