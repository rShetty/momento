"""OAuth2 authentication with automatic localhost callback capture."""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from urllib.parse import parse_qs, urlparse

import requests

from config import ROOT

CLIENT_SECRET_FILE = ROOT / "client_secret_282435778093-ig0kthatbvmprvbq6qg89inh74cbog2b.apps.googleusercontent.com.json"
TOKEN_FILE = ROOT / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_PORT = 8080
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"

auth_code = None


def _load_client_secret() -> dict:
    with open(CLIENT_SECRET_FILE) as f:
        data = json.load(f)
    if "web" in data:
        return data["web"]
    if "installed" in data:
        return data["installed"]
    raise ValueError("Unknown client_secret format")


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: green;">Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                </body></html>
            """)
        elif "error" in params:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            error = params["error"][0]
            self.wfile.write(f"""
                <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: red;">Authentication Failed</h1>
                <p>Error: {error}</p>
                </body></html>
            """.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass


def authenticate() -> None:
    """Run OAuth2 flow with automatic callback capture."""
    global auth_code
    auth_code = None
    
    client = _load_client_secret()
    client_id = client["client_id"]
    client_secret = client["client_secret"]
    auth_uri = client.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    token_uri = client.get("token_uri", "https://oauth2.googleapis.com/token")
    
    # Start local server to capture callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OAuthHandler)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    print("=" * 60)
    print("GMAIL OAUTH2 AUTHENTICATION")
    print("=" * 60)
    print()
    print("IMPORTANT: Make sure you have added this redirect URI to your")
    print("Google Cloud Console OAuth client:")
    print(f"   {REDIRECT_URI}")
    print()
    print("If you haven't, the authentication will fail with 'redirect_uri_mismatch'.")
    print()
    print("To add it:")
    print("1. Go to https://console.cloud.google.com/apis/credentials")
    print("2. Click your client ID")
    print("3. Add 'http://localhost:8080' under Authorized redirect URIs")
    print("4. Save")
    print()
    
    # Build auth URL with exact redirect_uri
    scope_str = " ".join(SCOPES)
    auth_url = (
        f"{auth_uri}?"
        f"client_id={client_id}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"scope={requests.utils.quote(scope_str)}&"
        f"response_type=code&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    
    print("Visiting auth URL in browser...")
    print(f"   {auth_url}")
    print()
    
    try:
        webbrowser.open(auth_url)
        print("(Browser opened)")
    except Exception:
        print("Please manually open the URL above")
    
    print()
    print("Waiting for authorization...")
    print("   (Accept the permissions in your browser)")
    print()
    
    # Wait for callback
    timeout = 120  # 2 minutes
    for i in range(timeout):
        if auth_code:
            break
        sleep(1)
        if i % 10 == 0 and i > 0:
            print(f"   ... waiting ({i}s)")
    
    server.shutdown()
    
    if not auth_code:
        print()
        print("❌ Timeout: No authorization received.")
        print()
        print("Troubleshooting:")
        print("   - If you saw 'redirect_uri_mismatch' in the browser:")
        print("     → Add 'http://localhost:8080' to Authorized redirect URIs")
        print("   - If you saw 'Access blocked':")
        print("     → Add your email as a Test user in OAuth consent screen")
        print("   - Check the browser URL for error messages")
        return
    
    print()
    print("✅ Authorization code received!")
    print()
    print("Exchanging code for tokens...")
    
    resp = requests.post(
        token_uri,
        data={
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    
    if resp.status_code != 200:
        print(f"❌ Token exchange failed: {resp.status_code}")
        print(resp.text)
        return
    
    tokens = resp.json()
    
    # Save token
    token_data = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": token_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": SCOPES,
    }
    
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    
    print()
    print("✅ Authentication successful!")
    print(f"   Token saved to: {TOKEN_FILE}")
    print(f"   Access token: {tokens['access_token'][:20]}...")
    if tokens.get("refresh_token"):
        print("   Refresh token: obtained (will auto-refresh)")
    print()
    print("You can now run: python main.py")


if __name__ == "__main__":
    authenticate()
