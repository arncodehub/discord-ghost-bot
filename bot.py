import discord
from discord.ext import commands, tasks
from discord import app_commands
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
intents.members = True
intents.voice_states = False


bot = commands.Bot(command_prefix='/', intents=intents)

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
    """Initial scan of guild history adaptive to the longest configured rule."""
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return
    
    # Find the maximum days requirement across all rules for this guild
    guild_config = config.get('guilds', {}).get(str(guild_id), {})
    rules = guild_config.get('rules', [])

    if not rules:
        print(f"[!] No rules found for {guild.name}, skipping scan.")
        return
    
    # Default to 30 if somehow empty, otherwise take the max 'days' value
    max_days = max([rule.get('days', 30) for rule in rules])

    print(f"Scanning message history for {guild.name} (last {max_days} days)...")
    guild_key = str(guild_id)
    
    if guild_key not in last_message_times:
        last_message_times[guild_key] = {}
    
    # Only scan last 90 days
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)
    
    # Scan all text channels
    for channel in guild.text_channels:
        try:
            print(f"  Scanning #{channel.name}...")
            message_count = 0
            async for message in channel.history(limit=None, after=cutoff_date):
                if not message.author.bot:
                    user_id = str(message.author.id)
                    message_time = message.created_at
                    
                    # Update user times
                    if user_id not in last_message_times[guild_key]:
                        last_message_times[guild_key][user_id] = message_time.isoformat()
                    else:
                        existing_time = datetime.fromisoformat(last_message_times[guild_key][user_id])
                        if message_time > existing_time:
                            last_message_times[guild_key][user_id] = message_time.isoformat()
                
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
            print(f"  HTTP error scanning #{channel.name}: {e}")
            continue
        
        # Small delay between channels
        await asyncio.sleep(2)
    
    # Scan all voice channels
    for channel in guild.voice_channels:
        try:
            print(f"  Scanning voice channel {channel.name}...")
            message_count = 0
            async for message in channel.history(limit=None, after=cutoff_date):
                if not message.author.bot:
                    user_id = str(message.author.id)
                    message_time = message.created_at
                    
                    # Update user times
                    if user_id not in last_message_times[guild_key]:
                        last_message_times[guild_key][user_id] = message_time.isoformat()
                    else:
                        existing_time = datetime.fromisoformat(last_message_times[guild_key][user_id])
                        if message_time > existing_time:
                            last_message_times[guild_key][user_id] = message_time.isoformat()
                
                message_count += 1
                # Save periodically to avoid losing progress
                if message_count % 1000 == 0:
                    save_message_times()
                    await asyncio.sleep(1)  # Rate limit protection
                    
        except discord.Forbidden:
            print(f"  No access to voice channel {channel.name}")
            continue
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                print(f"  Rate limited, waiting...")
                await asyncio.sleep(60)
                continue
            print(f"  HTTP error scanning voice channel {channel.name}: {e}")
            continue
        
        # Small delay between channels
        await asyncio.sleep(2)
    
    save_message_times()
    print(f"✓ Finished scanning {guild.name}")

async def update_inactive_role(guild_id, rules):
    """Update inactive roles for a guild based on multiple rules."""
    guild = bot.get_guild(int(guild_id))
    if not guild:
        print(f"ERROR: Guild {guild_id} not found!")
        return

    print(f"Checking inactive members for {guild.name}...")
    guild_key = str(guild_id)
    now = datetime.now(timezone.utc)
    
    if guild_key not in last_message_times:
        last_message_times[guild_key] = {}

    try:
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            
            user_id = str(member.id)
            user_last_seen_str = last_message_times[guild_key].get(user_id)
            
            if user_last_seen_str:
                last_message = datetime.fromisoformat(user_last_seen_str)
                if last_message.tzinfo is None:
                    last_message = last_message.replace(tzinfo=timezone.utc)
                days_inactive = (now - last_message).days
            else:
                # If never seen, treat as very inactive (e.g., 999 days)
                days_inactive = 999

            # Process each rule for this member
            for rule in rules:
                role_id = int(rule['role_id'])
                required_days = rule['days']
                role = guild.get_role(role_id)
                
                if not role:
                    continue

                if days_inactive >= required_days:
                    # Should have the role
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason=f"Inactive for {days_inactive} days")
                            print(f"  [+] {role.name} added to {member.name}")
                        except discord.Forbidden:
                            print(f"  [!] Missing permissions for {role.name} on {member.name}")
                else:
                    # Should NOT have the role
                    if role in member.roles:
                        try:
                            await member.remove_roles(role, reason=f"Active (Last seen {days_inactive} days ago)")
                            print(f"  [-] {role.name} removed from {member.name}")
                        except discord.Forbidden:
                            print(f"  [!] Missing permissions to remove {role.name}")

    except Exception as e:
        print(f"ERROR: Failed processing {guild.name}: {e}")

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
        rules = guild_config.get('rules', [])
        if rules:
            try:
                await update_inactive_role(guild_id, rules)
            except Exception as e:
                print(f"Error checking guild {guild_id}: {e}")

@check_all_guilds.before_loop
async def before_check():
    await bot.wait_until_ready()

@bot.tree.command(name="deadchannels", description="List channels with no recent activity")
@app_commands.describe(days="Number of days since last activity")
async def deadchannels(interaction: discord.Interaction, days: int):
    """Scan for dead channels in the guild."""
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=False)
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    dead_channels = []
    
    # Scan all text channels
    for channel in guild.text_channels:
        try:
            latest_message_time = None
            async for message in channel.history(limit=1):
                latest_message_time = message.created_at
                break
            
            if latest_message_time is None or latest_message_time < cutoff:
                dead_channels.append((channel, latest_message_time))
        except discord.Forbidden:
            # Can't read history, assume dead
            dead_channels.append((channel, None))
        except Exception as e:
            print(f"Error scanning {channel.name}: {e}")
    
    if not dead_channels:
        embed = discord.Embed(title=f"No dead channels in the last {days} days", color=0x00ff00)
    else:
        embed = discord.Embed(title=f"Dead channels (>{days} days inactive)", color=0xff0000)
        description = ""
        for channel, last_time in dead_channels:
            if last_time:
                days_ago = (datetime.now(timezone.utc) - last_time).days
                description += f"{channel.mention} - last message {days_ago} days ago\n"
            else:
                description += f"{channel.mention} - no recent activity or no access\n"
        embed.description = description
    
    await interaction.followup.send(embed=embed)

@bot.event
async def on_ready():
    print(f'✓ Bot logged in as {bot.user}')
    print(f'✓ Connected to {len(bot.guilds)} guilds')
    
    # Validate configuration
    print('\nValidating configuration...')
    for guild_id, guild_config in config.get('guilds', {}).items():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            print(f"ERROR: Guild {guild_id} not found!")
            continue
        
        rules = guild_config.get('rules', [])
        if not rules:
            print(f"ERROR: No 'rules' list found for guild {guild.name} ({guild.id})")
            continue
        
        for rule in rules:
            role_id = rule.get('role_id')
            days = rule.get('days')
            role = guild.get_role(int(role_id))

            if not role:
                print(f"ERROR: Role {role_id} not found in {guild.name}")
            else:
                print(f"✓ {guild.name} | Role: {role.name} ({days} days)")

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
    
    # Sync slash commands
    await bot.tree.sync()
    print("✓ Slash commands synced\n")

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
