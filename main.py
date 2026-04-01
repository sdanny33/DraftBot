import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError
import humanize

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

SCOPE = ['https://www.googleapis.com/auth/spreadsheets']
CREDS = Credentials.from_service_account_file('credentials.json', scopes=SCOPE)
CLIENT = gspread.authorize(CREDS)

SHEET_URL = os.getenv('GOOGLE_SHEET_URL')
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
WORKSHEET_NAME = os.getenv('GOOGLE_WORKSHEET_NAME', 'Sheet1')
WORKSHEET_NAME2 = os.getenv('GOOGLE_WORKSHEET_NAME2', 'Sheet2')

def _resolve_spreadsheet():
    if SHEET_URL:
        return CLIENT.open_by_url(SHEET_URL)
    if SHEET_ID:
        return CLIENT.open_by_key(SHEET_ID)
    raise RuntimeError(
        "Missing Google Sheet reference. Set GOOGLE_SHEET_URL or GOOGLE_SHEET_ID in .env"
    )

try:
    _SPREADSHEET = _resolve_spreadsheet()
    SHEET = _SPREADSHEET.worksheet(WORKSHEET_NAME)
    SHEET2 = _SPREADSHEET.worksheet(WORKSHEET_NAME2)
except APIError as e:
    raise SystemExit(f"Failed to access spreadsheet: {e}. Check GOOGLE_SHEET_URL/ID and worksheet name '{WORKSHEET_NAME}'.")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

async def mon_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    try:
        mons_list = SHEET2.col_values(8)  # Assuming column H (8) has the mons
        filtered = [
            app_commands.Choice(name=mon, value=mon)
            for mon in mons_list if mon and current.lower() in mon.lower()
        ][:25]  # Discord limits to 25 choices
        return filtered
    except Exception as e:
        print(f"Error fetching mons: {e}")
        return []

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} - {bot.user.id}')
    await bot.change_presence(status=discord.Status.online, activity=discord.Game('/helpme for commands'))
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

@bot.tree.command(name="leave", description="Leave a pick for yourself")
@app_commands.describe(mon="The pick you want to leave")
@app_commands.autocomplete(mon=mon_autocomplete)
async def leave(interaction: discord.Interaction, mon: str):
    if not check_pick(mon):
        await interaction.response.send_message('This pick is already taken.', ephemeral=True)
        return
    user_id = interaction.user.name
    row = [user_id, mon]
    SHEET.append_row(row)
    await interaction.response.send_message(f'Added your pick: {mon}', ephemeral=True)

@bot.tree.command(name="leavefor", description="Leave a pick for another user")
@app_commands.describe(mon="The pick to leave",user="The user's name")
@app_commands.autocomplete(mon=mon_autocomplete)
async def leavefor(interaction: discord.Interaction, mon: str, user: discord.User):
    name = user.name
    if not check_pick(mon):
        await interaction.response.send_message('This pick is already taken.', ephemeral=True)
        return
    row = [name, mon]
    SHEET.append_row(row)
    await interaction.response.send_message(f'Added {name}\'s pick: {mon}', ephemeral=True)

@bot.tree.command(name="pick", description="Retrieve your latest pick")
async def pick(interaction: discord.Interaction):
    all_rows = SHEET.get_all_values()
    name = interaction.user.name
    for row in all_rows:
        if len(row) > 0 and row[0] == name:
            await interaction.response.send_message(f"{name}'s pick is: {row[1]}")
            remove_row_index = all_rows.index(row) + 1
            SHEET.delete_rows(remove_row_index)
            return
    await interaction.response.send_message("You have no picks to retrieve.")

@bot.tree.command(name="pickfor", description="Retrieve another user's latest pick")
@app_commands.describe(user="The username to retrieve a pick for")
async def pickfor(interaction: discord.Interaction, user: discord.User):
    name = user.name
    all_rows = SHEET.get_all_values()
    for row in all_rows:
        if len(row) > 0 and row[0] == name:
            await interaction.response.send_message(f"{name}'s latest pick is: {row[1]}")
            remove_row_index = all_rows.index(row) + 1
            SHEET.delete_rows(remove_row_index)
            return
    await interaction.response.send_message(f"{name} has no picks to retrieve.")

@bot.tree.command(name="picks", description="View picks for a specific user")
@app_commands.describe(user="The username to check picks for")
async def picks(interaction: discord.Interaction, user: discord.User):
    name = user.name
    all_rows = SHEET.get_all_values()
    user_picks = [row[1] for row in all_rows if len(row) > 0 and row[0] == name]
    if user_picks:
        picks_list = '\n'.join(user_picks)
        await interaction.response.send_message(f'{name}\'s picks:\n{picks_list}', ephemeral=True)
    else:
        await interaction.response.send_message(f'{name} has no picks yet.', ephemeral=True)

@bot.tree.command(name="checkpick", description="Check if a pick is available")
@app_commands.describe(pick="The pick to check availability for")
@app_commands.autocomplete(pick=mon_autocomplete)
async def checkpick(interaction: discord.Interaction, pick: str):
    if check_pick(pick):
        await interaction.response.send_message(f"The pick '{pick}' is available.", ephemeral=True)
    else:
        await interaction.response.send_message(f"The pick '{pick}' is already taken.", ephemeral=True)

def check_pick(pick):
    all_rows = SHEET.get_all_values()
    for row in all_rows:
        if len(row) > 1 and row[1].lower() == pick.lower():
            return False
    return True
 
@bot.tree.command(name="time", description="Show time since the most recent message")
async def time(interaction: discord.Interaction):
    recent = None
    async for message in interaction.channel.history(limit=20):
        if message.id == interaction.id:
            continue
        recent = message
        break
    
    if not recent:
        await interaction.response.send_message("No previous messages found in this channel.")
        return
    
    elapsed = interaction.created_at - recent.created_at
    time_str = humanize.naturaltime(elapsed)
    
    await interaction.response.send_message(f"The most recent message was {time_str}.")

@bot.tree.command(name="timer", description="Start a countdown timer")
@app_commands.describe(seconds="Number of seconds for the timer")
async def timer(interaction: discord.Interaction, seconds: int):
    if seconds <= 0:
        await interaction.response.send_message("Please provide a positive number of seconds.", ephemeral=True)
        return
    await interaction.response.send_message(f"Starting a {seconds}-second timer!", ephemeral=True)
    await asyncio.sleep(seconds)
    await interaction.followup.send(f"{interaction.user.mention}, your {seconds}-second timer is up!", ephemeral=True)

@bot.tree.command(name="helpme", description="Show available commands")
async def helpme(interaction: discord.Interaction):
    help_text = (
        "Available commands:\n"
        "/leave <message> - Leave a pick for yourself.\n"
        "/leavefor <message> <user_id> - Leave a pick for another user.\n"
        "/pick - Retrieve and remove your latest pick.\n"
        "/pickfor <name> - Retrieve and remove another user's latest pick.\n"
        "/picks <name> - View picks for a specific user.\n"
        "/checkpick <pick> - Check if a pick is available.\n"
        "/time - Show the timestamp since the most recent message.\n"
        "/timer <seconds> - Start a countdown timer.\n"
        "/helpme - Show this help message.\n"
        "/shutdown - Shut down the bot.\n"
    )
    await interaction.response.send_message(help_text)

@bot.tree.command(name="shutdown", description="Shut down the bot (admin only)")
async def shutdown(interaction: discord.Interaction):
    await interaction.response.send_message("Shutting down...")
    await bot.close()

bot.run(TOKEN, log_handler=handler, log_level=logging.DEBUG)