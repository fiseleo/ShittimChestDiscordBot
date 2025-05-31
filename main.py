from dctoken import *
import discord
from discord.ext import commands
from discord import ui
import asyncio
from cogs.utils import get_gacha_data

import discord
from discord.ext import commands
import traceback
import os
# from dctoken import * # 假設您的 token 在這個檔案中

# 匯入我們統一的資料庫工具
from cogs.utils import get_gacha_data

# 在機器人啟動前，先執行一次資料庫初始化
print("正在初始化資料庫結構...")
get_gacha_data.initialize_database()
print("資料庫結構初始化完成。")

# 設定 Bot
intents = discord.Intents.default()
intents.message_content = True # 啟用訊息內容意圖，這樣 Bot 才能讀取訊息內容
# intents.message_content = True # 如果您有文字指令(!)，請取消此行註解
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