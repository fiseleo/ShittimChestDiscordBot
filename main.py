from dctoken import *
import discord
from discord.ext import commands
from cogs.utils import get_gacha_data # 依然需要 import
import traceback
import asyncio # 新增 import

# 設定 Bot
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

async def run_initial_database_setup():
    """執行首次資料庫檢查與更新"""
    print("檢查資料庫狀態並執行首次更新（如果需要）...")
    needs_update = True # 預設需要更新
    try:
        # 直接呼叫，因為這是啟動流程的一部分
        needs_update = not get_gacha_data.is_database_data_sufficient()
    except Exception as e:
        print(f"檢查資料庫狀態時發生錯誤: {e}，將執行首次更新。")

    if needs_update:
        print("資料庫資料不足或不存在，執行首次資料更新...")
        try:
            # 由於 get_gacha_data.update 是同步的，在 async on_ready 中用 run_in_executor
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, get_gacha_data.update)
            print("首次資料更新完成。")
        except Exception as e:
            print(f"首次資料更新時發生嚴重錯誤: {e}")
            # 考慮是否在這裡中止程式或進行其他錯誤處理
    else:
        print("資料庫已有足夠資料，跳過首次資料更新。")
    print("首次資料庫檢查與更新流程結束。")


@bot.event
async def on_ready():
    """當機器人準備就緒時執行。"""
    print(f'以 {bot.user.name} - {bot.user.id} 的身分登入')
    print('------')

    await run_initial_database_setup()

    
    initial_extensions = [
        'cogs.admin',
        'cogs.gacha', # 現在 gacha Cog 載入時，資料庫應該已經準備好了
        'cogs.update',
        'cogs.rps',
    ]
    
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            print(f"成功載入 Cog: {extension}")
        except Exception as e:
            print(f'載入 Cog {extension} 失敗.')
            traceback.print_exc()

bot.run(token_test)