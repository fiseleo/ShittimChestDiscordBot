from discord.ext import commands
import discord
from pathlib import Path

# --- 優化：權限管理 ---

ADMIN_ROLES_PATH = Path(__file__).parent.parent / "config/admin_roles.txt"
ADMIN_ROLES = []

try:
    with open(ADMIN_ROLES_PATH, "r", encoding="utf-8") as f:
        ADMIN_ROLES = [line for line in f.read().splitlines() if line]
except FileNotFoundError:
    print(f"警告：權限設定檔 '{ADMIN_ROLES_PATH}' 不存在。所有管理員指令將無法被任何人使用。")

def is_bot_admin():
    """一個可重用的檢查器，判斷指令使用者是否擁有管理員角色。"""
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild or not ADMIN_ROLES:
            return False
        author_role_names = {role.name for role in ctx.author.roles}
        return not author_role_names.isdisjoint(ADMIN_ROLES)
    return commands.check(predicate)

# --- Cog 主體 ---

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.command(name="reload", description="重新載入所有主要的 Cogs")
    @is_bot_admin()
    async def reload(self, ctx: commands.Context):
        # 從重載列表中移除 'cogs.raid'
        cogs_to_reload = ['cogs.admin', 'cogs.gacha', 'cogs.update', 'cogs.rps']
        reloaded_cogs = []
        failed_cogs = []
        for cog in cogs_to_reload:
            try:
                await self.bot.reload_extension(cog)
                reloaded_cogs.append(cog)
            except Exception as e:
                failed_cogs.append(f"{cog} ({e})")
        
        message = ""
        if reloaded_cogs:
            message += f"✅ 成功重新載入: `{'`, `'.join(reloaded_cogs)}`\n"
        if failed_cogs:
            message += f"❌ 載入失敗: `{'`, `'.join(failed_cogs)}`"
        await ctx.send(message)

    @commands.command(name="update", description="手動觸發資料庫更新")
    @is_bot_admin()
    async def update(self, ctx: commands.Context):
        await ctx.send("▶️ 正在手動觸發背景更新任務...")
        update_cog = self.bot.get_cog('UpdateTasks')
        if update_cog and hasattr(update_cog, 'update_data_loop'):
            await update_cog.update_data_loop()
            await ctx.send("✅ 背景更新任務已觸發完成。請查看主控台輸出確認進度。")
        else:
            await ctx.send("❌ 錯誤：找不到 'UpdateTasks' Cog 或更新迴圈。")

    @commands.command(name="sync", description="同步當前伺服器的斜線指令")
    @is_bot_admin()
    async def sync(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send("這個指令只能在伺服器中使用。")
        guild_obj = discord.Object(id=ctx.guild.id)
        self.bot.tree.copy_global_to(guild=guild_obj)
        synced = await self.bot.tree.sync(guild=guild_obj)
        await ctx.send(f"✅ 已同步 {len(synced)} 個指令到本伺服器。")

    @commands.command(name="sync-global", description="同步全域斜線指令")
    @is_bot_admin()
    async def sync_global(self, ctx: commands.Context):
        synced = await self.bot.tree.sync()
        await ctx.send(f"✅ 已同步 {len(synced)} 個全域指令。")

    # --- Raid 資料重置指令已被完全移除 ---

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))