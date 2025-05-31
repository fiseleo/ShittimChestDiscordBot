import asyncio
import datetime
from discord.ext import commands, tasks
import pytz

# 匯入我們最新的、統一的資料更新工具
from .utils import get_gacha_data

# 定義時區，方便日誌記錄
TIMEZONE = pytz.timezone('Asia/Taipei')

class UpdateTasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 當 Cog 載入時，自動啟動背景迴圈任務
        self.update_data_loop.start()

    def cog_unload(self):
        # 當 Cog 被卸載時，優雅地停止背景迴圈
        self.update_data_loop.cancel()

    @tasks.loop(hours=6)  # 設定迴圈間隔，例如每 6 小時執行一次
    async def update_data_loop(self):
        """主要的背景更新迴圈任務。"""
        print(f"[{datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}] 開始執行週期性資料更新...")
        
        # 獲取當前的 asyncio 事件迴圈
        loop = asyncio.get_running_loop()
        
        try:
            # 這是修正的核心：
            # 使用 run_in_executor 將同步的、耗時的 update 函式放到一個獨立的執行緒中執行。
            # 'None' 表示使用預設的 ThreadPoolExecutor。
            # 這樣主程式（機器人）就可以繼續運作，完全不會被卡住。
            await loop.run_in_executor(
                None, 
                get_gacha_data.update  # 呼叫我們新的、統一的更新函式
            )
            
            print(f"[{datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}] 資料更新完成，正在重新載入相關 Cogs...")

            # 重新載入依賴這些新資料的 Cog，讓它們能讀取到最新內容
            # 這裡可以根據需要新增更多要 reload 的 cog
            cogs_to_reload = ['cogs.gacha'] 
            for cog_name in cogs_to_reload:
                try:
                    await self.bot.reload_extension(cog_name)
                    print(f"成功重新載入 {cog_name}")
                except commands.ExtensionNotLoaded:
                    await self.bot.load_extension(cog_name) # 如果尚未載入，則載入
                    print(f"成功載入 {cog_name}")
                except Exception as e:
                    print(f"重新載入 {cog_name} 失敗: {e}")

        except Exception as e:
            print(f"執行更新任務時發生嚴重錯誤: {e}")

        print(f"[{datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}] 週期性資料更新結束。")

    @update_data_loop.before_loop
    async def before_update_loop(self):
        """在迴圈開始前執行的特殊函式，確保機器人已完全準備就緒。"""
        await self.bot.wait_until_ready()
        print("機器人已就緒，背景更新任務即將開始。")

async def setup(bot: commands.Bot):
    """Cog 的入口點，將這個 Cog 加入到機器人中。"""
    await bot.add_cog(UpdateTasks(bot))