from dotenv import load_dotenv, dotenv_values
import os

load_dotenv()

cache_file = 'prefetch_cache.json'
cache_ttl = 10800 # time for cache data to be considered valid; in seconds.

version = '0.2.81'

statuses = [f'version {version}']
twitch_user = 'example'

token = os.getenv('TOKEN')
now_playing_channel_id = os.getenv('NOW_PLAYING_CHANNEL_ID')