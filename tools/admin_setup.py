"""Create the admin console credentials.  Run on your own computer, never on the server:

    python tools/admin_setup.py

It prints three values for Render's Environment tab (ADMIN_USERNAME, ADMIN_PASSWORD_HASH, ADMIN_TOTP_SECRET)
and an otpauth:// link for your authenticator app (Google Authenticator, Aegis, 1Password, ...).
The password itself is never stored anywhere: only its scrypt hash goes to the server."""
import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import security  # noqa: E402

username = input("Admin username (not 'admin', pick something unique): ").strip()
if len(username) < 4 or username.lower() in {"admin", "administrator", "root"}:
    sys.exit("Pick a less guessable username (4+ characters, not admin/root).")
pw = getpass.getpass("Admin password (16+ characters, long passphrase is best): ")
if len(pw) < 14 or pw.lower() in security.COMMON_PASSWORDS:
    sys.exit("Password too short or too common. Use 14+ characters.")
if pw != getpass.getpass("Repeat password: "):
    sys.exit("Passwords did not match.")
secret = security.new_totp_secret()
print("\n--- put these three in Render -> Environment ---")
print(f"ADMIN_USERNAME={username}")
print(f"ADMIN_PASSWORD_HASH={security.hash_password(pw)}")
print(f"ADMIN_TOTP_SECRET={secret}")
print("\n--- add the 2FA to your authenticator app (manual entry or paste this link into a QR generator you trust) ---")
print(f"Secret key: {secret}")
print(security.otpauth_uri(secret, username))
print("\nThe console is at https://<your-site>/AnimeVoid . Optional hardening: ADMIN_IPS=your.ip.address")
