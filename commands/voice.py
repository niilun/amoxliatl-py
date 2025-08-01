import asyncio

import discord
import yt_dlp as youtube_dl
from datetime import datetime

from discord.ext import commands
from discord import app_commands

from constants import version, now_playing_channel_id

# supress errors
#youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume = 0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop = None, stream = False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download = not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data = data)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.is_playing = False
        self.current_voice_client = None

    async def play_next(self, guild):
        if self.queue:
            next_item = self.queue.pop(0)
            url = next_item['url']
            interaction = next_item['interaction']
            voice_client = guild.voice_client

            player = await YTDLSource.from_url(url, loop = asyncio.get_running_loop(), stream = True)
            voice_client.play(
                player,
                after = lambda e: asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)
            )
            
            channel = self.bot.get_channel(int(now_playing_channel_id))
            channel_name = player.data.get('uploader') or "Unknown channel"
            webpage_url = player.data.get('webpage_url') or 'Unknown uploader'

            response_embed = discord.Embed(
                title = player.title if player.title else "Unknown Title",
                description = f"Channel: {channel_name}\nLink: {webpage_url}",
                colour = discord.Color.from_rgb(0, 176, 244),
                timestamp = datetime.now()
            )
            response_embed.set_author(name = "Now playing")
            response_embed.set_footer(
                text = f"Amoxliatl v{version}",
                icon_url = "https://niilun.dev/images/amoxliatl.png"
            )
            
            if isinstance(channel, discord.TextChannel):
                await channel.send(content = None, embed = response_embed)
            else:
                print(f'There is an error with your now_playing channel configuration. Value is {now_playing_channel_id}')
            
            try:
                await interaction.followup.send(content = None, embed = response_embed, ephemeral = True)
            except Exception as e:
                await interaction.followup.send(f'An error occured while sending response:\n{e}', ephemeral = True)
        else:
            self.is_playing = False

    @app_commands.command(name = 'join', description = "Joins the user's voice channel")
    async def join(self, interaction: discord.Interaction, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""

        voice_client = interaction.guild.voice_client
        if voice_client is not None:
            return await voice_client.move_to(channel)

        await channel.connect()
        await interaction.response.send_message(f"Connected.", ephemeral = True)

    @app_commands.command(name = "play_youtube", description = "Plays audio from a YouTube URL or search parameter")
    async def play_youtube(self, interaction: discord.Interaction, url: str):
        """Slash command to play audio from a YouTube URL."""

        # Sanitize input
        if 'youtu.be' not in url and 'youtube.com' not in url:
            await interaction.response.send_message('This is not a valid URL.', ephemeral = True)
            return

        # Ensure user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral = True)
            return

        voice_client = interaction.guild.voice_client
        if not voice_client:
            # Connect to the user's voice channelz
            channel = interaction.user.voice.channel
            voice_client = await channel.connect()
        self.current_voice_client = voice_client

        await interaction.response.defer(thinking = True, ephemeral = True)

        # Add to queue
        self.queue.append({'url': url, 'interaction': interaction})

        if not self.is_playing:
            self.is_playing = True
            await self.play_next(interaction.guild)
        else:
            await interaction.followup.send(f"Added to queue, #{len(self.queue) + 1}", ephemeral = True)

    @app_commands.command(name = "skip", description = "Skips current song")
    async def skip(self, interaction: discord.Interaction):
        """Skips the current song"""
        await interaction.response.defer(thinking = True, ephemeral = True)

        voice_client = interaction.guild.voice_client

        if not voice_client or not voice_client.is_playing():
            await interaction.followup.send("Nothing is currently playing.", ephemeral = True)
            return

        if self.queue:
            voice_client.stop()
            await interaction.followup.send("Skipped to next song.", ephemeral = True)
        else:
            voice_client.stop()
            self.is_playing = False
            await interaction.followup.send("Stopped playback. No more songs in the queue.", ephemeral = True)
        
    @app_commands.command(name = "volume", description = "Change player volume")
    async def volume(self, interaction: discord.Interaction, volume: int):
        """Changes the player's volume"""

        voice_client = interaction.guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral = True)
            return

        if not voice_client.source:
            await interaction.response.send_message("Nothing is playing.", ephemeral = True)
            return

        voice_client.source.volume = volume / 100
        await interaction.response.send_message(f"Changed volume to {volume}%", ephemeral = True)

    @app_commands.command(name = "queue", description = "Shows the current queue")
    async def show_queue(self, interaction: discord.Interaction):
        """Shows the current queue"""
        if not self.queue:
            await interaction.response.send_message("The queue is empty.", ephemeral = True)
            return

        queue_list = []
        for idcount, item in enumerate(self.queue, start = 1):
            queue_list.append(f"{idcount}. [{item['name']}]({item['url']})")

        await interaction.response.send_message("Current queue:\n" + "\n".join(queue_list), ephemeral = True)

    @app_commands.command(name = "stop", description = "Stops playing")
    async def stop(self, interaction: discord.Interaction):
        """Stops and disconnects the bot from voice"""

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            self.queue.clear()
            self.is_playing = False
            await voice_client.disconnect()
            await interaction.response.send_message("Disconnected from the voice channel and cleared the queue.", ephemeral = True)
        else:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral = True)