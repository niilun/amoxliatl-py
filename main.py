import discord, asyncio, random
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv, dotenv_values

from commands.voice import Music

from constants import version, token, statuses

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

print(f'Amoxliatl version {version}')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands with Discord endpoints.')
    except Exception as e:
        print(f'Failed to sync commands, error {e}')
    change_status.start()

@tasks.loop(minutes=2)
async def change_status():
    await bot.change_presence(activity=discord.Streaming(name = random.choice(statuses), url = "https://twitch.tv/faiar"))

async def setup_cogs():
    await bot.add_cog(Music(bot))

async def main():
    async with bot:
        await setup_cogs()
        await bot.start(token)

asyncio.run(main())