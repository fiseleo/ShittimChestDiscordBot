from dctoken import *
import discord
from discord.ext import commands
from cogs.utils import get_gacha_data
from cogs.utils import get_gacha_data
import traceback

print("正在初始化資料庫結構...")
get_gacha_data.initialize_database()
print("資料庫結構初始化完成。")

# 設定 Bot
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """當機器人準備就緒時執行。"""
    print(f'以 {bot.user.name} - {bot.user.id} 的身分登入')
    print('------')
    
    # 載入所有需要的 Cogs
    initial_extensions = [
        'cogs.admin',
        'cogs.gacha',
        'cogs.update',
        'cogs.rps',
        # 'cogs.raid' 已被移除
    ]
    
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            print(f"成功載入 Cog: {extension}")
        except Exception as e:
            print(f'載入 Cog {extension} 失敗.')
            traceback.print_exc()

bot.run(token_test)