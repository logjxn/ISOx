import hashlib
import requests
import time
import argparse
import json
import os

## Functions for grabbing isos, computing hashes, comparing mirror speeds, and checksums
def download_file(url, destination_path):
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(destination_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
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
    fastest = max(results, key=results.get)  # note: max, not min
    return fastest


def main():
    parser = argparse.ArgumentParser(description="Download and verify Linux ISOs")
    parser.add_argument("distro", choices=["arch", "debian"], help="Which distro to download")
    args = parser.parse_args()

    with open("distros.json", "r") as f:
        distros = json.load(f)
    distro_info = distros[args.distro]
    mirrors = distro_info["mirrors"]
    checksum_filename = distro_info["checksum_filename"]
    hash_algo = distro_info["hash_algo"]

    os.makedirs("ISOx_Downloads", exist_ok=True)

    if args.distro == "arch":
        iso_filename = "archlinux-x86_64.iso"
    elif args.distro == "debian":
        peek_checksum_url = mirrors[0].rstrip("/") + "/" + checksum_filename
        response = requests.get(peek_checksum_url)
        response.raise_for_status()
        peek_lookup = {}
        for line in response.text.splitlines():
            parts = line.split()
            if len(parts) == 2:
                peek_lookup[parts[1]] = parts[0]
        iso_filename = next(f for f in peek_lookup if "netinst" in f and "amd64" in f)

    iso_urls = [m.rstrip("/") + "/" + iso_filename for m in mirrors]
    best_iso_url = find_fastest_mirror_by_throughput(iso_urls)
    base = best_iso_url.rsplit("/", 1)[0]

    checksum_url = f"{base}/{checksum_filename}"
    response = requests.get(checksum_url)
    response.raise_for_status()
    hash_lookup = {}
    for line in response.text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hash_lookup[parts[1]] = parts[0]

    destination_path = os.path.join("ISOx_Downloads", iso_filename)
    print(f"Downloading {iso_filename} from {base} ...")
    download_file(best_iso_url, destination_path)

    if verify_checksum(destination_path, iso_filename, hash_lookup, hash_algo):
        print("Checksum matches, file is good.")
    else:
        print("WARNING: checksum mismatch, file may be corrupted or tampered with!")

if __name__ == "__main__":
    main()
