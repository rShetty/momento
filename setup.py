#!/usr/bin/env python3
"""
KreditKard Setup Wizard

Run this after cloning the repo to get everything configured.
"""

import os
import subprocess
import sys
from pathlib import Path

def run(cmd, **kwargs):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def check_python():
    """Check Python version."""
    print("Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print(f"❌ Python {version.major}.{version.minor} found. Need 3.11+")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True

def setup_venv():
    """Create virtual environment."""
    print("\nSetting up virtual environment...")
    if Path(".venv").exists():
        print("✅ .venv already exists")
        return True
    
    out, err, code = run("python3 -m venv .venv")
    if code != 0:
        print(f"❌ Failed to create venv: {err}")
        return False
    
    print("✅ Virtual environment created")
    return True

def install_deps():
    """Install requirements."""
    print("\nInstalling dependencies...")
    
    pip_cmd = ".venv/bin/pip" if Path(".venv/bin/pip").exists() else ".venv/Scripts/pip"
    out, err, code = run(f"{pip_cmd} install -r requirements.txt")
    
    if code != 0:
        print(f"❌ Failed to install dependencies: {err}")
        return False
    
    print("✅ Dependencies installed")
    return True

def setup_env():
    """Create .env file from template."""
    print("\nSetting up environment file...")
    
    if Path(".env").exists():
        print("✅ .env already exists")
        return True
    
    if not Path(".env.example").exists():
        print("❌ .env.example not found")
        return False
    
    with open(".env.example") as f:
        template = f.read()
    
    with open(".env", "w") as f:
        f.write(template)
    
    print("✅ .env created from template")
    return True

def setup_telegram():
    """Guide user through Telegram bot creation."""
    print("\n" + "="*60)
    print("TELEGRAM BOT SETUP")
    print("="*60)
    print()
    print("1. Open Telegram and search for @BotFather")
    print("2. Send /newbot")
    print("3. Follow instructions to name your bot")
    print("4. BotFather will give you a token like:")
    print("   123456789:ABCdefGHIjklMNOpqrSTUvwxyz")
    print()
    
    token = input("Paste your Telegram bot token: ").strip()
    
    if not token or ":" not in token:
        print("❌ Invalid token format")
        return False
    
    # Update .env
    with open(".env", "r") as f:
        content = f.read()
    
    content = content.replace("TELEGRAM_BOT_TOKEN=", f"TELEGRAM_BOT_TOKEN={token}")
    
    with open(".env", "w") as f:
        f.write(content)
    
    print("✅ Token saved to .env")
    
    # Get chat ID
    print("\n5. Now message your bot /start")
    input("Press Enter after you've messaged the bot...")
    
    print("\nFetching your Chat ID...")
    
    # Use Python to get chat ID
    python_cmd = ".venv/bin/python" if Path(".venv/bin/python").exists() else ".venv/Scripts/python"
    
    script = f'''
import asyncio
from telegram import Bot

async def main():
    bot = Bot(token="{token}")
    updates = await bot.get_updates(limit=10)
    if updates:
        chat_id = updates[-1].message.chat.id
        print(f"CHAT_ID: {{chat_id}}")
        return chat_id
    return None

chat_id = asyncio.run(main())
'''
    
    out, err, code = run(f'{python_cmd} -c "{script}"')
    
    if code != 0 or "CHAT_ID:" not in out:
        print("❌ Could not fetch Chat ID. Make sure you messaged the bot /start")
        print(f"Error: {err}")
        return False
    
    chat_id = out.split("CHAT_ID:")[1].strip()
    
    # Update .env
    with open(".env", "r") as f:
        content = f.read()
    
    content = content.replace("TELEGRAM_CHAT_ID=", f"TELEGRAM_CHAT_ID={chat_id}")
    
    with open(".env", "w") as f:
        f.write(content)
    
    print(f"✅ Chat ID {chat_id} saved to .env")
    
    # Test message
    print("\nSending test message...")
    script = f'''
import asyncio
from telegram import Bot

async def main():
    bot = Bot(token="{token}")
    await bot.send_message(
        chat_id={chat_id},
        text="🤖 KreditKard Bot is online!",
        parse_mode="Markdown"
    )
    print("Message sent!")

asyncio.run(main())
'''
    
    out, err, code = run(f'{python_cmd} -c "{script}"')
    if code == 0:
        print("✅ Test message sent to Telegram")
    else:
        print(f"⚠️  Could not send test message: {err}")
    
    return True

def setup_gmail():
    """Guide user through Gmail OAuth setup."""
    print("\n" + "="*60)
    print("GMAIL OAUTH SETUP")
    print("="*60)
    print()
    print("You need a Gmail OAuth client secret. Options:")
    print()
    print("A) Use existing client_secret_*.json file")
    print("B) Create new Google Cloud project")
    print()
    
    choice = input("Choose (A/B): ").strip().upper()
    
    if choice == "A":
        files = list(Path(".").glob("client_secret_*.json"))
        if files:
            print(f"✅ Found: {files[0].name}")
            return True
        else:
            print("❌ No client_secret_*.json found in current directory")
            return False
    
    elif choice == "B":
        print("\nFollow these steps:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project")
        print("3. Enable Gmail API: APIs & Services → Library → Gmail API → Enable")
        print("4. Create OAuth credentials:")
        print("   APIs & Services → Credentials → Create Credentials → OAuth client ID")
        print("   Application type: Web application")
        print("   Name: KreditKard")
        print("   Authorized redirect URIs: http://localhost:8080")
        print("5. Download the JSON file")
        print("6. Place it in this directory")
        print()
        input("Press Enter when you've placed the file...")
        
        files = list(Path(".").glob("client_secret_*.json"))
        if files:
            print(f"✅ Found: {files[0].name}")
            return True
        else:
            print("❌ Still no client_secret_*.json found")
            return False
    
    else:
        print("❌ Invalid choice")
        return False

def run_auth():
    """Run Gmail authentication."""
    print("\n" + "="*60)
    print("GMAIL AUTHENTICATION")
    print("="*60)
    print()
    print("Running auth.py to authenticate with Gmail...")
    print()
    
    python_cmd = ".venv/bin/python" if Path(".venv/bin/python").exists() else ".venv/Scripts/python"
    
    # Run auth.py
    print("Launching OAuth flow...")
    print("(This will open a browser)")
    print()
    
    # We can't easily capture the auth flow here, so just instruct
    print("Please run this command manually:")
    print(f"  {python_cmd} auth.py")
    print()
    print("After auth.py completes successfully,")
    print("run 'python main.py' to test the full pipeline.")
    
    return True

def main():
    """Run the full setup wizard."""
    print("="*60)
    print("KREDITKARD SETUP WIZARD")
    print("="*60)
    print()
    
    # Check prerequisites
    if not check_python():
        sys.exit(1)
    
    # Setup virtual environment
    if not setup_venv():
        sys.exit(1)
    
    # Install dependencies
    if not install_deps():
        sys.exit(1)
    
    # Create .env
    if not setup_env():
        sys.exit(1)
    
    # Setup Telegram
    if not setup_telegram():
        print("⚠️  Telegram setup incomplete. You can re-run this later.")
    
    # Setup Gmail
    if not setup_gmail():
        print("⚠️  Gmail setup incomplete.")
    else:
        run_auth()
    
    print("\n" + "="*60)
    print("SETUP COMPLETE")
    print("="*60)
    print()
    print("Next steps:")
    print("1. Run: python auth.py  (to complete Gmail OAuth)")
    print("2. Run: python main.py  (to test full pipeline)")
    print("3. Run: python telegram_bot.py  (to start bot for commands)")
    print()
    print("For cron setup, see README.md")

if __name__ == "__main__":
    main()
