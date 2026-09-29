"""Make the ADMIN_PASSWORD_HASH value for your admin password.

Run:  python make_password.py
Then paste the printed line into your .env file, and paste the part inside the quotes
into Railway > your service > Variables > ADMIN_PASSWORD_HASH.
"""
from getpass import getpass

from werkzeug.security import generate_password_hash

while True:
    pw = getpass("New admin password (at least 6 characters, hidden as you type): ")
    if len(pw) < 6:
        print("Too short. Use at least 6 characters.")
        continue
    if getpass("Type it again: ") != pw:
        print("The two passwords don't match. Try again.")
        continue
    break

print()
print(f"ADMIN_PASSWORD_HASH='{generate_password_hash(pw)}'")
