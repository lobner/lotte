#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.parse

WRANGLER_CONFIG_PATH = os.path.expanduser("~/.wrangler/config/default.toml")
CLIENT_ID = "5a2f58e4-18c6-43b9-a20c-0cc51cf5719e"

def print_banner(text):
    print("=" * 60)
    print(text.center(60))
    print("=" * 60)

def refresh_oauth_token(refresh_token):
    print("[*] Attempting to refresh Cloudflare OAuth token...")
    url = "https://dash.cloudflare.com/oauth2/token"
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print("[+] Token refreshed successfully!")
            return res_data.get("access_token")
    except Exception as e:
        print(f"[-] Failed to refresh OAuth token: {e}")
        return None

def get_cloudflare_token():
    # 1. Check if token is in environment
    env_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if env_token:
        print("[+] Using Cloudflare API token from environment variable CLOUDFLARE_API_TOKEN.")
        return env_token

    # 2. Check Wrangler configuration
    if os.path.exists(WRANGLER_CONFIG_PATH):
        try:
            print(f"[*] Found Wrangler configuration at {WRANGLER_CONFIG_PATH}")
            oauth_token = None
            refresh_tok = None
            with open(WRANGLER_CONFIG_PATH, "r") as f:
                for line in f:
                    if line.startswith("oauth_token"):
                        oauth_token = line.split("=")[1].strip().strip('"').strip("'")
                    elif line.startswith("refresh_token"):
                        refresh_tok = line.split("=")[1].strip().strip('"').strip("'")
            
            # Try to verify the oauth token first
            if oauth_token:
                req = urllib.request.Request(
                    "https://api.cloudflare.com/client/v4/user/tokens/verify",
                    headers={"Authorization": f"Bearer {oauth_token}"}
                )
                try:
                    with urllib.request.urlopen(req) as resp:
                        res = json.loads(resp.read().decode())
                        if res.get("success") and res.get("result", {}).get("status") == "active":
                            print("[+] Wrangler OAuth token is active and valid.")
                            return oauth_token
                except Exception:
                    print("[*] Saved OAuth token expired/invalid. Trying to refresh using refresh token...")
            
            if refresh_tok:
                new_token = refresh_oauth_token(refresh_tok)
                if new_token:
                    # Update config file if possible
                    # (We won't block on writing back, but we return the token)
                    return new_token
        except Exception as e:
            print(f"[-] Error reading Wrangler config: {e}")

    # 3. Prompt user as fallback
    print("\n[-] No valid token found in environment or wrangler configuration.")
    print("Please generate a Cloudflare API token with 'Zone.DNS' edit permissions.")
    print("Go to: https://dash.cloudflare.com/profile/api-tokens")
    user_token = input("Enter your Cloudflare API Token: ").strip()
    if not user_token:
        print("[-] API token is required to proceed.")
        sys.exit(1)
    return user_token

def make_api_request(url, token, method="GET", data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    body = None
    if data:
        body = json.dumps(data).encode("utf-8")
        
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        error_content = e.read().decode()
        try:
            return json.loads(error_content)
        except Exception:
            return {"success": False, "errors": [{"message": f"HTTP Error {e.code}: {e.reason}"}]}
    except Exception as e:
        return {"success": False, "errors": [{"message": str(e)}]}

def main():
    print_banner("Cloudflare Subdomain Creator: lotte.lobner.dk")
    
    token = get_cloudflare_token()
    
    # Step 1: Get Zone ID for lobner.dk
    print("[*] Fetching Zone ID for lobner.dk...")
    zone_url = "https://api.cloudflare.com/client/v4/zones?name=lobner.dk"
    res = make_api_request(zone_url, token)
    
    if not res.get("success") or not res.get("result"):
        print("[-] Failed to retrieve Zone ID. Errors:")
        for err in res.get("errors", []):
            print(f"    - {err.get('message')}")
        print("\n[!] Please ensure your API Token has 'Zone.Zone' read permissions.")
        sys.exit(1)
        
    zone = res["result"][0]
    zone_id = zone["id"]
    print(f"[+] Found Zone ID for lobner.dk: {zone_id}")
    
    # Step 2: Check if lotte.lobner.dk CNAME record already exists
    print("[*] Checking for existing CNAME records for lotte.lobner.dk...")
    dns_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name=lotte.lobner.dk&type=CNAME"
    res = make_api_request(dns_url, token)
    
    if not res.get("success"):
        print("[-] Failed to check DNS records. Errors:")
        for err in res.get("errors", []):
            print(f"    - {err.get('message')}")
        sys.exit(1)
        
    records = res.get("result", [])
    if records:
        record = records[0]
        print(f"[+] CNAME record for lotte.lobner.dk already exists (points to: {record['content']}).")
        if record["content"] == "lobner.github.io":
            print("[+] DNS is already correctly configured!")
            sys.exit(0)
        else:
            choice = input(f"[?] Update existing CNAME record target from '{record['content']}' to 'lobner.github.io'? (y/n): ").strip().lower()
            if choice != 'y':
                print("[*] Aborted updating record.")
                sys.exit(0)
                
            # Update existing record
            print("[*] Updating CNAME record...")
            update_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}"
            payload = {
                "type": "CNAME",
                "name": "lotte.lobner.dk",
                "content": "lobner.github.io",
                "ttl": 1,
                "proxied": True
            }
            res = make_api_request(update_url, token, method="PUT", data=payload)
            if res.get("success"):
                print("[+] CNAME record updated successfully!")
            else:
                print("[-] Failed to update CNAME record. Errors:")
                for err in res.get("errors", []):
                    print(f"    - {err.get('message')}")
            sys.exit(0)

    # Step 3: Create CNAME record
    print("[*] Creating CNAME record for lotte.lobner.dk pointing to lobner.github.io...")
    create_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    payload = {
        "type": "CNAME",
        "name": "lotte.lobner.dk",
        "content": "lobner.github.io",
        "ttl": 1,
        "proxied": True
    }
    res = make_api_request(create_url, token, method="POST", data=payload)
    
    if res.get("success"):
        print("[+] CNAME record created successfully!")
        print("[+] CNAME: lotte.lobner.dk -> lobner.github.io (Proxied)")
    else:
        print("[-] Failed to create CNAME record. Errors:")
        for err in res.get("errors", []):
            print(f"    - {err.get('message')}")
        print("\n[!] Please ensure your API Token has 'Zone.DNS' edit permissions.")
        print("[!] Manual setup fallback details:")
        print("    - Type: CNAME")
        print("    - Name: lotte")
        print("    - Target: lobner.github.io")
        print("    - Proxy Status: Proxied (or DNS only)")

if __name__ == "__main__":
    main()
