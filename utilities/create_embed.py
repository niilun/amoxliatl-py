import discord
from datetime import datetime

from discord import Embed

def create_embed(title: str = '', description: str = '', colour: discord.colour = None, timestamp = None, author_name: str = None, author_url: str = None, footer_name: str = None, footer_url: str = None) -> discord.Embed:
    if not colour:
        colour = discord.colour.random()
    
    if not timestamp:
        timestamp = datetime.now()
    
    embed = discord.Embed(
        title = title,
        description = description,
        colour = colour,
        timestamp = timestamp
    )

    if author_name or author_url:
        embed.set_author(
            name = author_name if author_name else '',
            url = author_url if author_url else ''
        )

    if footer_name or footer_url:
        embed.set_footer(
            text=footer_name if footer_name else '',
            icon_url=footer_url if footer_url else ''
        )

    return embed