import asyncio
import datetime
from discord.ext import commands, tasks
import pytz

from .utils import get_gacha_data # 確保 get_gacha_data 有 is_database_data_sufficient 函式

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
        self.bot.loop.create_task(self.initial_update())

    async def initial_update(self):
        """Cog 啟動時，檢查資料庫並視情況執行的首次資料更新。"""
        await self.bot.wait_until_ready()
        log_time = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        
        loop = asyncio.get_running_loop()
        
        # --- 修改：檢查資料庫是否需要初始化資料 ---
        try:
            needs_initial_update = not await loop.run_in_executor(None, get_gacha_data.is_database_data_sufficient)
        except Exception as e:
            print(f"[{log_time}] 檢查資料庫狀態時發生錯誤: {e}，將執行首次更新。")
            needs_initial_update = True # 保守起見，出錯則執行更新

        if needs_initial_update:
            print(f"[{log_time}] 資料庫資料不足或不存在，執行首次資料更新...")
            try:
                await loop.run_in_executor(None, get_gacha_data.update)
                log_time_after_update = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{log_time_after_update}] 首次資料更新完成，嘗試重新載入 gacha Cog...")
                try:
                    await self.bot.reload_extension('cogs.gacha')
                    print("首次更新後成功重新載入 cogs.gacha")
                except Exception as e:
                    print(f"首次更新後重新載入 cogs.gacha 失敗: {e}")
            except Exception as e:
                print(f"首次資料更新時發生嚴重錯誤: {e}")
        else:
            print(f"[{log_time}] 資料庫已有足夠資料，跳過首次資料更新。")
        
        log_time_end = datetime.datetime.now(TAIPEI_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{log_time_end}] 首次資料更新檢查流程結束。")
    # --- 修改結束 ---

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
                    await self.bot.reload_extension(cog_name)
                    print(f"成功重新載入 {cog_name}")
                except Exception as e:
                    print(f"重新載入 {cog_name} 失敗: {e}")
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