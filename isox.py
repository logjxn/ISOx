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
    hasher = hashlib.new(algo)  # dynamically picks sha256, sha512, etc.
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
    
def check_mirror_speed(url):
    try:
        start = time.time()
        response = requests.head(url, timeout=5)
        response.raise_for_status()
        elapsed = time.time() - start
        return elapsed
    except requests.exceptions.RequestException:
        return None # Mirror down or unreachable
    
def find_fastest_mirror(mirror_urls):
    results = {}
    for url in mirror_urls:
        speed = check_mirror_speed(url)
        if speed is not None:
            results[url] = speed
            print(f"{url} responded in {speed:.3f}s")
        else:
            print(f"{url} is unreachable")
    if not results:
        raise Exception("No reachable mirrors")
    fastest = min(results, key=results.get)
    return fastest


def main():
    parser = argparse.ArgumentParser(description="Download and verify Linux ISOs")
    parser.add_argument("distro", choices=["arch", "debian"], help="Which distro to download")
    args = parser.parse_args()

    # Load distro config
    with open("distros.json", "r") as f:
        distros = json.load(f)
    distro_info = distros[args.distro]

    mirrors = distro_info["mirrors"]
    checksum_filename = distro_info["checksum_filename"]
    hash_algo = distro_info["hash_algo"]

    os.makedirs("ISOx_Downloads", exist_ok=True)

    # Build full checksum URLs for each mirror, then race them
    checksum_urls = [m.rstrip("/") + "/" + checksum_filename for m in mirrors]
    best_checksum_url = find_fastest_mirror(checksum_urls)
    base = best_checksum_url.rsplit("/", 1)[0]

    # Fetch and parse the checksum file
    response = requests.get(best_checksum_url)
    response.raise_for_status()
    hash_lookup = {}
    for line in response.text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hash_lookup[parts[1]] = parts[0]

    if args.distro == "arch":
        iso_filename = "archlinux-x86_64.iso"
    elif args.distro == "debian":
        iso_filename = next(f for f in hash_lookup if "netinst" in f and "amd64" in f)

    iso_url = f"{base}/{iso_filename}"
    destination_path = os.path.join("ISOx_Downloads", iso_filename)

    print(f"Downloading {iso_filename} from {base} ...")
    download_file(iso_url, destination_path)

    if verify_checksum(destination_path, iso_filename, hash_lookup, hash_algo):
        print("Checksum matches, file is good.")
    else:
        print("WARNING: checksum mismatch, file may be corrupted or tampered with!")

if __name__ == "__main__":
    main()