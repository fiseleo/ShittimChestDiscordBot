import asyncio
import datetime
from discord.ext import commands, tasks
import pytz

from .utils import get_gacha_data

TAIPEI_TIMEZONE = pytz.timezone('Asia/Taipei')
UTC_PLUS_9 = pytz.timezone('Etc/GMT-9')

class UpdateTasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        update_times = [
            datetime.time(hour=0, minute=0, tzinfo=UTC_PLUS_9),
            datetime.time(hour=12, minute=0, tzinfo=UTC_PLUS_9),
            datetime.time(hour=18, minute=0, tzinfo=UTC_PLUS_9),
        ]
        
        self.update_data_loop.change_interval(time=update_times)
        self.update_data_loop.start()

    def cog_unload(self):
        self.update_data_loop.cancel()

    @tasks.loop()
    async def update_data_loop(self):
        log_time = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{log_time}] 開始執行排程資料更新...")
        
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, get_gacha_data.update)
            
            log_time_after_update = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{log_time_after_update}] 資料更新完成，正在重新載入相關 Cogs...")

            cogs_to_reload = ['cogs.gacha'] 
            for cog_name in cogs_to_reload:
                try:
                    # 如果 gacha Cog 之前因故未載入，reload 會失敗，嘗試 load
                    try:
                        await self.bot.reload_extension(cog_name)
                        print(f"成功重新載入 {cog_name}")
                    except commands.ExtensionNotLoaded:
                        print(f"{cog_name} 尚未載入，嘗試直接載入...")
                        await self.bot.load_extension(cog_name)
                        print(f"成功載入 {cog_name}")
                except Exception as e:
                    print(f"處理 Cog {cog_name} 失敗: {e}")
        except Exception as e:
            print(f"執行更新任務時發生嚴重錯誤: {e}")

        log_time_end = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{log_time_end}] 排程資料更新結束。")

    @update_data_loop.before_loop
    async def before_update_loop(self):
        await self.bot.wait_until_ready()
        print("機器人已就緒，背景更新排程任務即將開始。")

async def setup(bot: commands.Bot):
    await bot.add_cog(UpdateTasks(bot))