from dotenv import load_dotenv, dotenv_values
import os

load_dotenv()

version = '0.2.1'

statuses = [f'version {version}']

token = os.getenv('TOKEN')
now_playing_channel_id = os.getenv('NOW_PLAYING_CHANNEL_ID')