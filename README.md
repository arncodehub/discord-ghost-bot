# Ghost - Discord Inactive Role Bot

A Discord bot that manages an "inactive" role for members who haven't sent any messages in the last 30 days.

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your bot token
4. Copy `example.json` to `config.json` add edit it to include the guild IDs and role IDs
5. Run the bot: `python bot.py`

## Configuration

### .env
```
DISCORD_TOKEN=your_bot_token_here
```

### config.json
```json
{
  "guilds": {
    "GUILD_ID": {
      "role_id": "ROLE_ID"
    }
  }
}
```

## Permissions

The bot needs the following permissions:
- Manage Roles
- View Channels
- Read Message History

The bot needs the following privileged gateway intents:
- Server Members Intent
- Message Content Intent

## How It Works

The bot runs a daily check on all configured guilds. For each member, it scans all text channels to see if they've sent any messages in the last 30 days. Members with no messages receive the configured role, and members who have sent messages lose it.
