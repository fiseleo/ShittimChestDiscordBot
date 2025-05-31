import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import random
import math
import PIL.Image
import PIL.ImageChops
# 匯入我們新的資料庫查詢工具
from .utils import gacha_db

# 將路徑設定移到 Cog 內部或作為全域常數
ASSETS_DIR = Path(__file__).parent.parent / "assets"
IMAGE_DIR = Path(__file__).parent.parent / "gacha_data" / "images"

# 預先載入不會變動的圖片資源
try:
    MASK = PIL.Image.open(ASSETS_DIR / "mask.png")
    BORDER = PIL.Image.open(ASSETS_DIR / "border.png")
    STAR_1 = PIL.Image.open(ASSETS_DIR / "star.png")
    STAR_2 = PIL.Image.open(ASSETS_DIR / "two_star.png")
    STAR_3 = PIL.Image.open(ASSETS_DIR / "three_star.png")
    PURPLE_GLOW = PIL.Image.open(ASSETS_DIR / "purple_glow.png")
    YELLOW_GLOW = PIL.Image.open(ASSETS_DIR / "yellow_glow.png")
    PICKUP = PIL.Image.open(ASSETS_DIR / "pickup.png")
except FileNotFoundError as e:
    raise FileNotFoundError(f"缺少核心素材圖片，請檢查 assets 資料夾: {e}")


# --- Gacha Cog 主體 ---

class Gacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 在 Cog 初始化時，從資料庫載入所有資料到記憶體中
        self.load_data_from_db()

    def load_data_from_db(self):
        """從資料庫載入並快取角色池和卡池資訊。"""
        print("正在從資料庫載入轉蛋資料...")
        self.pools_gl = gacha_db.get_character_pools("global")
        self.banners_gl = gacha_db.get_current_banners("global")
        
        self.pools_jp = gacha_db.get_character_pools("japan")
        self.banners_jp = gacha_db.get_current_banners("japan")
        
        # 將 Fes 限定池從一般限定池中分離出來 (如果需要)
        # 這裡簡化處理，假設所有限定都在一個池裡，由抽卡邏輯決定
        print("轉蛋資料載入完成。")

    def pull_logic(self, server: str, choice: int, last_pull: bool):
        """核心抽卡邏輯，決定抽出的角色。"""
        pools = self.pools_gl if server == "global" else self.pools_jp
        banners = self.banners_gl if server == "global" else self.banners_jp
        
        # 複製卡池以避免修改原始快取資料
        pool_r = pools["R"].copy()
        pool_sr = pools["SR"].copy()
        pool_ssr = pools["SSR"].copy()
        pool_limited = pools["Limited"].copy()

        pickup_sr, pickup_ssr = [], []
        
        # R, SR, SSR, Pickup_SR, Pickup_SSR
        weights = [78.5, 18.5, 3.0, 0, 0]
        gacha_type = "PermanentGacha"

        if choice > -1 and choice < len(banners):
            banner = banners[choice]
            gacha_type = banner["gachaType"]
            
            # 從卡池中移除 UP 角，放入 UP 池
            for rateup in banner["rateups"]:
                rateup_id = rateup["id"]
                if rateup["rarity"] == "SR":
                    pool_sr = [char for char in pool_sr if char["id"] != rateup_id]
                    pickup_sr.append(rateup)
                else: # SSR
                    pool_ssr = [char for char in pool_ssr if char["id"] != rateup_id]
                    pool_limited = [char for char in pool_limited if char["id"] != rateup_id]
                    pickup_ssr.append(rateup)

            # 根據卡池類型調整權重
            if gacha_type == "PickupGacha":
                if pickup_sr:
                    weights[1] -= 3.0
                    weights[3] += 3.0
                if pickup_ssr:
                    weights[2] -= 0.7 * len(pickup_ssr)
                    weights[4] += 0.7 * len(pickup_ssr)
            elif gacha_type == "LimitedGacha":
                if pickup_ssr:
                    weights[2] -= 0.7 * len(pickup_ssr)
                    weights[4] += 0.7 * len(pickup_ssr)
            elif gacha_type == "FesGacha":
                weights = [75.5, 18.5, 5.3, 0, 0.7] # 總計 6% SSR，0.7% UP
        
        # 十連保底 SR
        if last_pull:
            weights[1] += weights[0]
            weights[0] = 0

        # 抽卡
        try:
            rarity_result = random.choices(["R", "SR", "SSR", "Pickup_SR", "Pickup_SSR"], weights)[0]
            
            result = {}
            if rarity_result == "R" and pool_r:
                result = random.choice(pool_r)
                result["rarity"] = "R"
            elif rarity_result == "SR" and pool_sr:
                result = random.choice(pool_sr)
                result["rarity"] = "SR"
            elif rarity_result == "SSR" and pool_ssr:
                result = random.choice(pool_ssr)
                result["rarity"] = "SSR"
            elif rarity_result == "Pickup_SR" and pickup_sr:
                result = random.choice(pickup_sr)
                result["rarity"] = "Pickup_SR"
            elif rarity_result == "Pickup_SSR" and pickup_ssr:
                result = random.choice(pickup_ssr)
                result["rarity"] = "Pickup_SSR"
            else: # 如果目標池為空，則從 R 池遞補
                result = random.choice(pool_r)
                result["rarity"] = "R"

            result["server"] = server
            return result
        except IndexError: # 當所有卡池都為空時的極端情況
            return {"id": 0, "name": "神秘的卷軸", "rarity": "R", "server": server}
    
    def create_single_image(self, result: dict):
        """根據抽卡結果生成單張角色頭像圖。"""
        base_char_image = PIL.Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        
        try:
            # 圖片路徑現在統一使用 ID
            char_img_path = IMAGE_DIR / f"{result['id']}.png"
            with PIL.Image.open(char_img_path) as char:
                char = char.convert("RGBA")
                char = PIL.ImageChops.multiply(char, MASK)
                base_char_image.alpha_composite(char, (20, 20))
        except FileNotFoundError:
            print(f"警告：找不到學生圖片 {result['id']}.png")

        rarity = result["rarity"]
        if rarity == "R":
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_1)
        elif rarity in ("SR", "Pickup_SR"):
            base_char_image.alpha_composite(YELLOW_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_2)
            if rarity == "Pickup_SR":
                base_char_image.alpha_composite(PICKUP)
        elif rarity in ("SSR", "Pickup_SSR"):
            base_char_image.alpha_composite(PURPLE_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_3)
            if rarity == "Pickup_SSR":
                base_char_image.alpha_composite(PICKUP)
                
        return base_char_image

    def generate_gacha_image(self, results: list):
        """將多張角色頭像圖合成一張大的結果圖。"""
        char_images = [self.create_single_image(res) for res in results]
        
        image_count = len(char_images)
        if image_count > 1:
            cols = 5
            rows = math.ceil(image_count / cols)
            base_image = PIL.Image.new("RGBA", (cols * 120 + 40, rows * 140), (194, 229, 245, 255))
            for i, img in enumerate(char_images):
                base_image.alpha_composite(img, (i % cols * 120, i // cols * 140))
        else:
            base_image = PIL.Image.new("RGBA", (640, 300), (194, 229, 245, 255))
            base_image.alpha_composite(char_images[0], (240, 70))
            
        base_image.save("result.png")

    @app_commands.command(name="gacha", description="模擬抽卡")
    @app_commands.describe(mode="選擇一次招募的數量")
    @app_commands.choices(mode=[
        app_commands.Choice(name="單抽", value="single"),
        app_commands.Choice(name="十抽", value="ten")
    ])
    async def gacha(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        """主斜線指令，顯示卡池選擇介面。"""
        view = GachaView(cog=self, mode=mode.value)
        await interaction.response.send_message("請選擇您要進行招募的卡池：", view=view, ephemeral=True)


# --- UI 元件 ---

class GachaDropdown(discord.ui.Select):
    def __init__(self, cog: Gacha, mode: str):
        self.cog = cog
        self.mode = mode
        
        options = []
        # 國際服卡池
        for i, banner in enumerate(self.cog.banners_gl):
            banner_name = " & ".join([r["name"] for r in banner["rateups"]])
            options.append(discord.SelectOption(label=f"國際服：{banner_name}", value=f"global_{i}"))
        options.append(discord.SelectOption(label="國際服：常駐招募", value="global_-1"))

        # 日服卡池
        for i, banner in enumerate(self.cog.banners_jp):
            banner_name = " & ".join([r["name"] for r in banner["rateups"]])
            options.append(discord.SelectOption(label=f"日服：{banner_name}", value=f"japan_{i}"))
        options.append(discord.SelectOption(label="日服：常駐招募", value="japan_-1"))

        super().__init__(placeholder="選擇卡池", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        server, choice_str = self.values[0].split("_")
        choice = int(choice_str)

        if self.mode == "single":
            results = [self.cog.pull_logic(server, choice, False)]
        else: # ten
            results = [self.cog.pull_logic(server, choice, i == 9) for i in range(10)]
        
        self.cog.generate_gacha_image(results)
        
        banner_name = "常駐招募"
        banners = self.cog.banners_gl if server == "global" else self.cog.banners_jp
        if choice > -1:
            banner_name = " & ".join([r["name"] for r in banners[choice]["rateups"]])

        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if server == 'global' else '日服'}\n**卡池：** {banner_name}",
            color=discord.Color.blue()
        )
        file = discord.File("result.png", filename="result.png")
        embed.set_image(url="attachment://result.png")
        
        view = GachaView(cog=self.cog, mode=self.mode, server=server, choice=choice, is_button=True)
        await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)


class GachaButton(discord.ui.Button):
    def __init__(self, cog: Gacha, mode: str, server: str, choice: int):
        super().__init__(label="再抽一次！", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.mode = mode
        self.server = server
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        # 與 Dropdown 的 callback 執行幾乎相同的邏輯
        await interaction.response.defer()
        
        if self.mode == "single":
            results = [self.cog.pull_logic(self.server, self.choice, False)]
        else: # ten
            results = [self.cog.pull_logic(self.server, self.choice, i == 9) for i in range(10)]
            
        self.cog.generate_gacha_image(results)

        banner_name = "常駐招募"
        banners = self.cog.banners_gl if self.server == "global" else self.cog.banners_jp
        if self.choice > -1:
             banner_name = " & ".join([r["name"] for r in banners[self.choice]["rateups"]])

        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if self.server == 'global' else '日服'}\n**卡池：** {banner_name}",
            color=discord.Color.blue()
        )
        file = discord.File("result.png", filename="result.png")
        embed.set_image(url="attachment://result.png")
        
        view = GachaView(cog=self.cog, mode=self.mode, server=self.server, choice=self.choice, is_button=True)
        await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)


class GachaView(discord.ui.View):
    def __init__(self, cog: Gacha, mode: str, server: str = "global", choice: int = -1, is_button: bool = False):
        super().__init__(timeout=300) # 5分鐘後 view 會失效
        if is_button:
            self.add_item(GachaButton(cog, mode, server, choice))
        else:
            self.add_item(GachaDropdown(cog, mode))


# --- Cog 設定 ---

async def setup(bot: commands.Bot):
    await bot.add_cog(Gacha(bot))
    print("Gacha cog has been reloaded and is now using the database.")