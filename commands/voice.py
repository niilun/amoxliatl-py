import asyncio

import discord
import yt_dlp

# cache stuff
import json, os, time

from datetime import datetime

from discord.ext import commands
from discord import app_commands

from constants import version, now_playing_channel_id, cache_file, cache_ttl

from utilities.create_embed import create_embed

# supress errors
# yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'sleep_interval_requests': 1.0,
    'ratelimit': 50000,
    'source_address': '0.0.0.0', # bind to ipv4 so we don't get buggy ipv6
    'geo_bypass': True,
    'cachedir': False
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume = 0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop = None, stream = False):
        loop = loop or asyncio.get_event_loop()

        # extract() handles getting fresh information so URLs don't expire on us
        def extract():
            return ytdl.extract_info(url, download= False)

        data = await loop.run_in_executor(None, extract)

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)

        source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
        return cls(source, data=data)
    
    @classmethod
    async def get_info(cls, url, *, loop = None):
        try:
            loop = loop or asyncio.get_event_loop()

            def extract():
                return ytdl.extract_info(url, download= False)
            
            data = await loop.run_in_executor(None, extract)
            if 'entries' in data:
                data = data['entries'][0]
            return data
        except Exception as e:
            print(f'Error in {__name__}: {e}')

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.is_playing = False
        self.clean_cache()

    # song prefetch
    async def prefetch(self, url: str):
        '''Prefetches info for the next song in queue'''
        loop = asyncio.get_running_loop()
        cache = self.load_cache()
        key = self.get_cache_key(url)

        # check if cache has data for the key already
        cache_data = cache.get(key)
        # if data is not expired, return it
        if cache_data and time.time() - cache_data.get('timestamp', 0) < cache_ttl:
            return cache_data['data']
        
        def extract():
            return ytdl.extract_info(url, download = False)
        
        try:
            data = await loop.run_in_executor(None, extract)
            if 'entries' in data:
                data = data['entries'][0]
            
            final_data = {
                'title': data.get('title'),
                'webpage_url': data.get('webpage_url'),
                'uploader': data.get('uploader'),
                'stream_url': data['url']
            }

            # save data to cache
            cache[key] = {'timestamp': time.time(), 'data': final_data}
            self.save_cache(cache)
            return final_data
        except Exception as e:
            print(f'Prefetch error for video {url}: {e}')
            return None

    # cache loading/saving
    def load_cache(self):
        '''Loads the cache saved in cache_file.'''
        if not os.path.exists(cache_file):
            return {}
        try:
            with open(cache_file, 'r', encoding = 'utf-8') as file:
                return json.load(file)
        except Exception:
            return {}

    def save_cache(self, cache: dict):
        '''Saves the dict in cache in the cache file defined in cache_file.'''
        try:
            with open(cache_file, 'w', encoding = 'utf-8') as file:
                json.dump(cache, file)
        except Exception as e:
            print(f'Cache dump failed! Error: {e}')
    
    def get_cache_key(self, url: str):
        '''Converts a url into its ID form, to be used in the cache.'''
        if 'v=' in url:
            # remove everything after v= and after the & for extra data
            return url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            # if it's a youtu.be link get everything after the slash and before the ? for extra data
            return url.split('youtu.be/')[1].split('?')[0]
    
    def clean_cache(self):
        '''Deletes expired entries from cache.'''
        try:
            cache = self.load_cache()
            now = time.time()

            updated = {key: value for key, value in cache.items() if now - value.get("timestamp", 0) < cache_ttl}
            if len(updated) != len(cache):
                self.save_cache(updated)
        except Exception as e:
            print(f'Cache cleanup failed! {e}')

    async def play_next(self, guild: discord.Guild):
        '''Plays the next item in the queue.'''
        if not self.queue:
            self.is_playing = False
            return

        next_item = self.queue.pop(0)
        interaction = next_item['interaction']
        voice_client = guild.voice_client

        # if client is disconnected stop playback
        if not voice_client or not voice_client.is_connected():
            self.is_playing = False
            return

        prefetch_task = next_item.get('prefetch')
        data = None
        if prefetch_task:
            try:
                data = await asyncio.wait_for(prefetch_task, timeout=10)
            except Exception as e:
                print(f"Prefetch failed: {e}")

        if not data:
            data = await self.prefetch(next_item['url'])

        stream_url = data.get('stream_url') or data.get('url')
        source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)
        player = YTDLSource(source, data=data)

        def after_playback(err):
            if err:
                print(f'Playback error: {err}')
            # schedule next track
            asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)

        voice_client.play(player, after=after_playback)

        # send the now_playing message
        channel = self.bot.get_channel(int(now_playing_channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(now_playing_channel_id))
            except Exception as e:
                print(f'Error fetching now playing channel: {e}')
                return

        channel_name = player.data.get('uploader', 'Unknown channel')
        webpage_url = player.data.get('webpage_url', 'Unknown URL')

        response_embed = create_embed(
            title = player.title or 'Unknown Title',
            description = f'Channel: {channel_name}\nLink: {webpage_url}',
            colour = discord.Colour.from_rgb(0, 176, 244),
            timestamp = datetime.now(),
            author_name = f'Now playing',
            author_url = None,
            footer_name = f'Amoxliatl v{version}',
            footer_url = 'https://niilun.dev/images/amoxliatl.png'
        )

        if isinstance(channel, discord.TextChannel):
            await channel.send(embed = response_embed)

        # notify interaction user if possible
        try:
            await interaction.followup.send(content=None, embed=response_embed, ephemeral=True)
        except discord.errors.InteractionResponded:
            pass
        except Exception as e:
            print(f'Error sending interaction follow-up: {e}')

        # prefetch next track if possible
        if self.queue:
            next = self.queue[0]
            if not next.get('prefetch'):
                next['prefetch'] = asyncio.create_task(self.prefetch(next['url']))


    @app_commands.command(name = 'join', description = 'Joins a selected channel.')
    async def join(self, interaction: discord.Interaction, *, channel: discord.VoiceChannel):
        '''Joins a voice channel'''

        try:
            voice_client = interaction.guild.voice_client
            if voice_client is not None:
                return await voice_client.move_to(channel)

            await channel.connect()
            await interaction.response.send_message(f'Connected.', ephemeral = True)
        except Exception as e:
            await interaction.response.send_message(f'Error: {e}')
            print(f'Error in {__name__}: {e}')

    @app_commands.command(name='play_youtube', description='Plays audio from a YouTube URL')
    async def play_youtube(self, interaction: discord.Interaction, url: str):
        '''Slash command to play audio from a YouTube URL.'''

        # sanitize input
        valid_domains = ['youtube.com', 'youtu.be', 'music.youtube.com']
        if not any(domain in url for domain in valid_domains):
            await interaction.response.send_message('This is not a valid URL.', ephemeral=True)
            return

        # ensure user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('You are not connected to a voice channel.', ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if not voice_client:
            # connect to the user's voice channel
            channel = interaction.user.voice.channel
            voice_client = await channel.connect()

        self.current_voice_client = voice_client

        # defer early so as to not hit the limit
        await interaction.response.defer(thinking=True, ephemeral=True)

        # create a prefetch task
        prefetch_task = asyncio.create_task(self.prefetch(url))

        # add all the info to the queue
        self.queue.append({'url': url, 'prefetch': prefetch_task, 'interaction': interaction})

        # if nothing is playing, start playback
        if not self.is_playing:
            self.is_playing = True
            asyncio.create_task(self.play_next(interaction.guild))
            await interaction.followup.send('Starting playback...', ephemeral=True)
            return

        # if player is active, fetch info and send message informing queue added
        try:
            song_info = await asyncio.wait_for(YTDLSource.get_info(url, loop=asyncio.get_running_loop()), timeout=15)
            song_name = song_info.get('title', 'Unknown title')
            song_channel = song_info.get('uploader', 'Unknown channel')
            song_url = song_info.get('webpage_url', url)
        except asyncio.TimeoutError:
            await interaction.followup.send('Timeout while fetching song info.', ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f'Error fetching song info: {e}', ephemeral=True)
            return

        response_embed = create_embed(
            title=song_name,
            description=f'Channel: {song_channel}\nLink: {song_url}',
            colour=discord.Colour.from_rgb(0, 176, 244),
            timestamp=datetime.now(),
            author_name = f'{interaction.user.display_name} added to queue',
            author_url = interaction.user.display_avatar.url,
            footer_name = f'Amoxliatl v{version}',
            footer_url = 'https://niilun.dev/images/amoxliatl.png'
        )

        # Send ephemeral follow-up to the user
        await interaction.followup.send(f'Added to queue, yours is #{len(self.queue)}', ephemeral=True)

        # Send embed to now playing channel
        channel = self.bot.get_channel(int(now_playing_channel_id))
        if channel is None:
            channel = await self.bot.fetch_channel(int(now_playing_channel_id))
        await channel.send(content=None, embed=response_embed)

    @app_commands.command(name = 'skip', description = 'Skips current song')
    async def skip(self, interaction: discord.Interaction):
        '''Skips the current song'''
        await interaction.response.defer(thinking = True, ephemeral = True)

        voice_client = interaction.guild.voice_client
        channel = self.bot.get_channel(int(now_playing_channel_id))
        if channel is None:
            channel = await self.bot.fetch_channel(int(now_playing_channel_id))
        
        if not voice_client or not voice_client.is_playing():
            await interaction.followup.send('Nothing is currently playing.', ephemeral = True)
            return

        if self.queue:
            # build an embed announcing who skipped the current song
            await interaction.followup.send('Skipped to next song.', ephemeral = True)
            current_title = 'Unknown Title'
            if voice_client and getattr(voice_client, 'source', None):
                current_title = getattr(voice_client.source, 'title', None) \
                    or (getattr(voice_client.source, 'data', {}) or {}).get('title') \
                    or 'Unknown Title'

            response_embed = create_embed(
                title = current_title,
                colour = discord.Colour.from_rgb(0, 176, 244),
                timestamp = datetime.now(),
                author_name = f'{interaction.user.display_name} skipped current song',
                author_url = interaction.user.display_avatar.url,
                footer_name = f'Amoxliatl v{version}',
                footer_url = 'https://niilun.dev/images/amoxliatl.png',
            )

            voice_client.stop()
            if isinstance(channel, discord.TextChannel):
                await channel.send(content = None, embed = response_embed)
        else:
            await interaction.followup.send('Skipped and stopped playback.', ephemeral = True)
            voice_client.stop()
            self.is_playing = False

            response_embed = create_embed(
                title = 'Stopped playback. No more songs in the queue.',
                colour = discord.Colour.from_rgb(0, 176, 244),
                timestamp = datetime.now(),
                author_name = None,
                author_url = None,
                footer_name = f'Amoxliatl v{version}',
                footer_url = 'https://niilun.dev/images/amoxliatl.png',
            )

            if isinstance(channel, discord.TextChannel):
                await channel.send(content = None, embed = response_embed)
        
    @app_commands.command(name = 'volume', description = 'Changes player volume')
    async def volume(self, interaction: discord.Interaction, volume: int):
        '''Changes the player's volume'''

        voice_client = interaction.guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            await interaction.response.send_message('Not connected to a voice channel.', ephemeral = True)
            return

        if not voice_client.source:
            await interaction.response.send_message('Nothing is playing.', ephemeral = True)
            return

        voice_client.source.volume = volume / 100
        await interaction.response.send_message(f'Changed volume to {volume}%', ephemeral = True)

    @app_commands.command(name = 'queue', description = 'Shows the current queue')
    async def show_queue(self, interaction: discord.Interaction):
        '''Shows the current queue for the interaction\'s guild.'''
        if not self.queue:
            response_embed = create_embed(
                title = 'The queue is empty.',
                colour = discord.Colour.from_rgb(0, 176, 244),
                timestamp = datetime.now(),
                author_name = None,
                author_url = None,
                footer_name = f'Amoxliatl v{version}',
                footer_url = 'https://niilun.dev/images/amoxliatl.png',
            )
            
            await interaction.response.send_message(content = None, embed = response_embed, ephemeral = True)
            return

        queue_list = []
        for idcount, item in enumerate(self.queue, start = 1):
            # queue items may not have a name, so try getting name -> title -> url in that order
            display_name = item.get('name') or item.get('title') or item.get('url')
            item_url = item.get('url') or display_name
            queue_list.append(f'{idcount}. {item_url}')

        response_embed = create_embed(
            title = f'Current queue for {interaction.guild.name}',
            description = '\n'.join(queue_list),
            colour = discord.Colour.from_rgb(0, 176, 244),
            timestamp = datetime.now(),
            author_name = None,
            author_url = None,
            footer_name = f'Amoxliatl v{version}',
            footer_url = 'https://niilun.dev/images/amoxliatl.png',
        )

        await interaction.response.send_message(content = None, embed = response_embed, ephemeral = True)

    @app_commands.command(name = 'stop', description = 'Stops playback and clears the queue.')
    async def stop(self, interaction: discord.Interaction):
        '''Stops and disconnects the bot from voice.'''

        voice_client = interaction.guild.voice_client
        channel = self.bot.get_channel(int(now_playing_channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(now_playing_channel_id))
            except Exception as e:
                print(f'Error fetching now playing channel: {e}')
                return
        
        channel_name = interaction.guild.voice_client.channel.name if interaction.guild.voice_client and interaction.guild.voice_client.channel else 'Unknown'

        response_embed = create_embed(
            title = '',
            description = f'Left {channel_name}',
            colour = discord.Colour.from_rgb(0, 176, 244),
            timestamp = datetime.now(),
            author_name = f'{interaction.user.display_name} stopped playback',
            author_url = interaction.user.display_avatar.url,
            footer_name = None,
            footer_url = None
        )
        
        if voice_client and voice_client.is_connected():
            self.queue.clear()
            self.is_playing = False
            await voice_client.disconnect()
            await interaction.response.send_message('Disconnected from the voice channel and cleared the queue.', ephemeral = True)
            if isinstance(channel, discord.TextChannel):
                await channel.send(content = None, embed = response_embed)
        else:
            await interaction.response.send_message('Not connected to a voice channel.', ephemeral = True)