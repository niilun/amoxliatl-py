import discord
from datetime import datetime

from discord.ext import commands
from discord import Embed

def create_embed(title: str, description: str, color: discord.Color = 0, timestamp = 0, author_name: str = '', author_url: str = '', footer_name: str = '', footer_url: str = '') -> discord.Embed:
    if color == 0:
        color = discord.Color.random()
    
    if timestamp == 0:
        timestamp = datetime.now()
    
    embed = discord.Embed(
        title = title,
        description = description,
        color = color,
        timestamp = timestamp
    )

    if author_name:
        embed.set_author(name = author_name)
    if author_url:
        embed.set_author(url = author_url)
    if footer_name:
        embed.set_footer(name = footer_name)
    if footer_url:
        embed.set_footer(url = footer_url)

    return embed