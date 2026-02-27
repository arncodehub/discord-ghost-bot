import discord
from discord.ext import tasks
import json
import asyncio
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    print("✓ Config loaded successfully")
except FileNotFoundError:
    print("ERROR: config.json not found!")
    exit(1)
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in config.json: {e}")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = discord.Client(intents=intents)

# Track last message time for each user in each guild
last_message_times = {}

def load_message_times():
    """Load message times from file."""
    global last_message_times
    try:
        with open('message_times.json', 'r') as f:
            last_message_times = json.load(f)
    except FileNotFoundError:
        last_message_times = {}

def save_message_times():
    """Save message times to file."""
    with open('message_times.json', 'w') as f:
        json.dump(last_message_times, f, indent=2)

async def scan_guild_history(guild_id):
    """Initial scan of guild message history (last 30 days)."""
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return
    
    print(f"Scanning message history for {guild.name} (last 30 days)...")
    guild_key = str(guild_id)
    
    if guild_key not in last_message_times:
        last_message_times[guild_key] = {}
    
    # Only scan last 30 days
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Scan all text channels
    for channel in guild.text_channels:
        try:
            print(f"  Scanning #{channel.name}...")
            message_count = 0
            async for message in channel.history(limit=None, after=cutoff_date):
                if not message.author.bot:
                    user_id = str(message.author.id)
                    message_time = message.created_at.isoformat()
                    
                    # Update if this is the most recent message we've seen
                    if user_id not in last_message_times[guild_key]:
                        last_message_times[guild_key][user_id] = message_time
                    else:
                        existing_time = datetime.fromisoformat(last_message_times[guild_key][user_id])
                        if message.created_at > existing_time:
                            last_message_times[guild_key][user_id] = message_time
                
                message_count += 1
                # Save periodically to avoid losing progress
                if message_count % 1000 == 0:
                    save_message_times()
                    await asyncio.sleep(1)  # Rate limit protection
                    
        except discord.Forbidden:
            print(f"  No access to #{channel.name}")
            continue
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                print(f"  Rate limited, waiting...")
                await asyncio.sleep(60)
                continue
            print(f"  HTTP error scanning #{chaname}: {e}")
            continue
        
        # Small delay between channels
        await asyncio.sleep(2)
    
    save_message_times()
    print(f"✓ Finished scanning {guild.name}")

async def update_inactive_role(guild_id, role_id):
    """Update the inactive role for a guild."""
    guild = bot.get_guild(int(guild_id))
    if not guild:
        print(f"ERROR: Guild {guild_id} not found! Bot may not be in this server.")
        return

    role = guild.get_role(int(role_id))
    if not role:
        print(f"ERROR: Role {role_id} not found in guild '{guild.name}' ({guild_id})!")
        print(f"  Available roles in {guild.name}:")
        for r in guild.roles:
            print(f"    - {r.name} (ID: {r.id})")
        return

    print(f"Checking inactive members for {guild.name}")
    
    # Calculate cutoff date (30 days ago)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
    guild_key = str(guild_id)
    
    if guild_key not in last_message_times:
        last_message_times[guild_key] = {}

    members_to_add = []
    members_to_remove = []

    # Check each member
    try:
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            
            user_id = str(member.id)
            
            # Check if user has sent messages recently
            if user_id in last_message_times[guild_key]:
                last_message = datetime.fromisoformat(last_message_times[guild_key][user_id])
                # Make timezone aware if needed
                if last_message.tzinfo is None:
                    last_message = last_message.replace(tzinfo=timezone.utc)
                
                has_recent_messages = last_message > cutoff_date
            else:
                # No messages tracked, assume inactive
                has_recent_messages = False

            if has_recent_messages:
                if role in member.roles:
                    members_to_remove.append(member)
            else:
                if role not in member.roles:
                    members_to_add.append(member)
    except discord.Forbidden:
        print(f"ERROR: Missing 'Server Members Intent' permission for guild {guild.name}")
        return
    except Exception as e:
        print(f"ERROR: Failed to fetch members for {guild.name}: {e}")
        return

    # Add members who should have the role
    for member in members_to_add:
        try:
            await member.add_roles(role, reason="No messages in last 30 days")
            print(f"  Added role to {member.name}")
        except discord.Forbidden:
            print(f"  ERROR: Cannot add role to {member.name} - missing 'Manage Roles' permission")
        except Exception as e:
            print(f"  ERROR: Failed to add role to {member.name}: {e}")

    # Remove members who should not have the role
    for member in members_to_remove:
        try:
            await member.remove_roles(role, reason="Has sent messages in last 30 days")
            print(f"  Removed role from {member.name}")
        except discord.Forbidden:
            print(f"  ERROR: Cannot remove role from {member.name} - missing 'Manage Roles' permission")
        except Exception as e:
            print(f"  ERROR: Failed to remove role from {member.name}: {e}")
    
    print(f"✓ Finished: +{len(members_to_add)} inactive, -{len(members_to_remove)} active")

@bot.event
async def on_message(message):
    """Track when users send messages."""
    if message.author.bot or not message.guild:
        return
    
    guild_key = str(message.guild.id)
    user_id = str(message.author.id)
    
    if guild_key not in last_message_times:
        last_message_times[guild_key] = {}
    
    last_message_times[guild_key][user_id] = message.created_at.isoformat()
    save_message_times()

@tasks.loop(hours=24)
async def check_all_guilds():
    """Check all configured guilds for inactive members."""
    for guild_id, guild_config in config.get('guilds', {}).items():
        role_id = guild_config.get('role_id')
        if role_id:
            try:
                await update_inactive_role(guild_id, role_id)
            except Exception as e:
                print(f"Error checking guild {guild_id}: {e}")

@check_all_guilds.before_loop
async def before_check():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f'✓ Bot logged in as {bot.user}')
    print(f'✓ Connected to {len(bot.guilds)} guilds')
    
    # Validate configuration
    print('\nValidating configuration...')
    for guild_id, guild_config in config.get('guilds', {}).items():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            print(f"  ERROR: Guild {guild_id} not found! Bot is not in this server.")
            continue
        
        role_id = guild_config.get('role_id')
        if not role_id:
            print(f"  ERROR: No role_id specified for guild {guild.name} ({guild_id})")
            continue
        
        role = guild.get_role(int(role_id))
        if not role:
            print(f"  ERROR: Role {role_id} not found in guild {guild.name}")
            print(f"    Available roles:")
            for r in guild.roles:
                print(f"      - {r.name} (ID: {r.id})")
        else:
            print(f"  ✓ Guild: {guild.name} | Role: {role.name}")
    
    print('\n------')
    
    # Load existing message times
    load_message_times()
    
    # Always re-scan on startup to catch up during downtime
    for guild_id in config.get('guilds', {}).keys():
        await scan_guild_history(guild_id)
    
    # Start the background task
    if not check_all_guilds.is_running():
        check_all_guilds.start()
        print("✓ Background task started\n")

# Run the bot
token = os.getenv('DISCORD_TOKEN')
if not token:
    print("ERROR: DISCORD_TOKEN not found in .env file!")
    exit(1)

try:
    bot.run(token)
except discord.LoginFailure:
    print("ERROR: Invalid bot token! Check your DISCORD_TOKEN in .env")
    exit(1)
except Exception as e:
    print(f"ERROR: Failed to start bot: {e}")
    exit(1)
