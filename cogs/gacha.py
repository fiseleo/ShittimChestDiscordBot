import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import random
import math
import PIL.Image
import PIL.ImageChops
from .utils import gacha_db

ASSETS_DIR = Path(__file__).parent.parent / "assets"
IMAGE_DIR = Path(__file__).parent.parent / "gacha_data" / "images" 

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


class Gacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.load_data_from_db()

    def load_data_from_db(self):
        """從資料庫載入並快取角色池和卡池資訊。"""
        print("正在從資料庫載入轉蛋資料...")
        self.pools_gl = gacha_db.get_character_pools("global")
        self.banners_gl = gacha_db.get_current_banners("global")
        
        self.pools_jp = gacha_db.get_character_pools("japan")
        self.banners_jp = gacha_db.get_current_banners("japan")
        
        print("轉蛋資料載入完成。")

    def pull_logic(self, server: str, choice: int, last_pull: bool):
        """改進的核心抽卡邏輯，正確處理所有卡池類型和機率。"""
        pools = self.pools_gl if server == "global" else self.pools_jp
        banners = self.banners_gl if server == "global" else self.banners_jp
        
        # 建立基礎卡池副本
        pool_r = pools["R"].copy()
        pool_sr = pools["SR"].copy()
        pool_ssr = pools["SSR"].copy()
        pool_limited = pools["Limited"].copy()
        pool_fes = pools["Fes"].copy()

        # 初始化pickup卡池和權重
        pickup_sr, pickup_ssr, pickup_fes = [], [], []
        
        # 基礎權重: [R, SR, SSR, Pickup_SR, Pickup_SSR, Pickup_Fes, Limited_Other, Fes_Other]
        weights = [78.5, 18.5, 3.0, 0, 0, 0, 0, 0]
        gacha_type = "NormalGacha"
        
        # 處理特定卡池
        if choice > -1 and choice < len(banners):
            banner = banners[choice]
            gacha_type = banner["gachaType"]
            
            # 處理pickup角色
            for rateup in banner["rateups"]:
                rateup_id = rateup["id"]
                rateup_char = None
                
                # 從對應的卡池中找到並移除pickup角色
                if rateup["rarity"] == "SR":
                    for char in pool_sr:
                        if char["id"] == rateup_id:
                            rateup_char = char.copy()
                            pool_sr.remove(char)
                            break
                    if rateup_char:
                        pickup_sr.append(rateup_char)
                else:  # SSR
                    # 先檢查常駐SSR池
                    for char in pool_ssr:
                        if char["id"] == rateup_id:
                            rateup_char = char.copy()
                            pool_ssr.remove(char)
                            break
                    
                    # 如果沒找到，檢查限定池
                    if not rateup_char:
                        for char in pool_limited:
                            if char["id"] == rateup_id:
                                rateup_char = char.copy()
                                pool_limited.remove(char)
                                break
                    
                    # 如果還沒找到，檢查Fes池
                    if not rateup_char:
                        for char in pool_fes:
                            if char["id"] == rateup_id:
                                rateup_char = char.copy()
                                pool_fes.remove(char)
                                break
                    
                    # 根據角色類型加入對應的pickup池
                    if rateup_char:
                        # 判斷是否為Fes角色 (假設Fes角色的is_limited為3)
                        if any(char["id"] == rateup_id for char in pools["Fes"]):
                            pickup_fes.append(rateup_char)
                        else:
                            pickup_ssr.append(rateup_char)

            # 根據卡池類型調整權重
            if gacha_type == "PickupGacha":
                # 常駐pickup卡池
                if pickup_sr:
                    weights[1] -= 3.0  # 普通SR減少3%
                    weights[3] += 3.0  # Pickup SR增加3%
                if pickup_ssr:
                    pickup_rate = 0.7 * len(pickup_ssr)
                    weights[2] -= pickup_rate  # 普通SSR減少
                    weights[4] += pickup_rate  # Pickup SSR增加
                    
            elif gacha_type == "LimitedGacha":
                # 限定pickup卡池
                if pickup_ssr:
                    pickup_rate = 0.7 * len(pickup_ssr)
                    weights[2] -= pickup_rate  # 普通SSR減少
                    weights[4] += pickup_rate  # Pickup SSR增加
                    
                    # 限定卡池可以抽到其他同期限定角色
                    if pool_limited:
                        limited_rate = pickup_rate * 0.3  # 其他限定角色機率較低
                        weights[2] -= limited_rate
                        weights[6] += limited_rate  # Limited_Other
                        
            elif gacha_type == "FesGacha":
                # Fes卡池：總SSR機率翻倍到6%
                total_ssr_rate = 6.0
                weights[0] = 75.5  # R機率降低到75.5%
                weights[1] = 18.5  # SR機率保持18.5%
                
                if pickup_fes:
                    pickup_fes_rate = 0.7 * len(pickup_fes)
                    weights[5] = pickup_fes_rate  # Pickup Fes
                    
                    # 其他Fes角色平分剩餘機率
                    remaining_fes_count = len(pool_fes)
                    if remaining_fes_count > 0:
                        other_fes_rate = min(0.9, (total_ssr_rate - pickup_fes_rate) * 0.2)
                        weights[7] = other_fes_rate  # Fes_Other
                        remaining_ssr_rate = total_ssr_rate - pickup_fes_rate - other_fes_rate
                    else:
                        remaining_ssr_rate = total_ssr_rate - pickup_fes_rate
                        
                    weights[2] = max(0, remaining_ssr_rate)  # 常駐SSR
                else:
                    weights[2] = total_ssr_rate  # 全部給常駐SSR

        # 十連保底：最後一抽必出SR以上
        if last_pull:
            weights[1] += weights[0]  # SR機率增加R的機率
            weights[0] = 0  # R機率設為0

        # 執行抽卡
        try:
            categories = ["R", "SR", "SSR", "Pickup_SR", "Pickup_SSR", "Pickup_Fes", "Limited_Other", "Fes_Other"]
            rarity_result = random.choices(categories, weights)[0]
            
            result = {}
            
            if rarity_result == "R" and pool_r:
                result = random.choice(pool_r).copy()
                result["rarity"] = "R"
            elif rarity_result == "SR" and pool_sr:
                result = random.choice(pool_sr).copy()
                result["rarity"] = "SR"
            elif rarity_result == "SSR" and pool_ssr:
                result = random.choice(pool_ssr).copy()
                result["rarity"] = "SSR"
            elif rarity_result == "Pickup_SR" and pickup_sr:
                result = random.choice(pickup_sr).copy()
                result["rarity"] = "Pickup_SR"
            elif rarity_result == "Pickup_SSR" and pickup_ssr:
                result = random.choice(pickup_ssr).copy()
                result["rarity"] = "Pickup_SSR"
            elif rarity_result == "Pickup_Fes" and pickup_fes:
                result = random.choice(pickup_fes).copy()
                result["rarity"] = "Pickup_Fes"
            elif rarity_result == "Limited_Other" and pool_limited:
                result = random.choice(pool_limited).copy()
                result["rarity"] = "Limited_Other"
            elif rarity_result == "Fes_Other" and pool_fes:
                result = random.choice(pool_fes).copy()
                result["rarity"] = "Fes_Other"
            else:
                # 容錯處理：如果選中的池子是空的，回退到R池
                if pool_r:
                    result = random.choice(pool_r).copy()
                    result["rarity"] = "R"
                else:
                    result = {"id": 0, "name": "Null", "rarity": "Error"}

            result["server"] = server
            return result
            
        except (IndexError, ValueError) as e:
            print(f"抽卡邏輯錯誤: {e}")
            return {"id": 0, "name": "Null", "rarity": "Error", "server": server}
    
    def create_single_image(self, result: dict):
        """根據抽卡結果生成單張角色頭像圖。"""
        base_char_image = PIL.Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        
        try:
            char_img_path = IMAGE_DIR / f"{result['id']}.png"
            with PIL.Image.open(char_img_path) as char_pil_img:
                char_pil_img = char_pil_img.convert("RGBA")
                char_pil_img = PIL.ImageChops.multiply(char_pil_img, MASK)
                base_char_image.alpha_composite(char_pil_img, (20, 20))
        except FileNotFoundError:
            print(f"警告：找不到學生圖片 {result['id']}.png for {result['name']}")
        except Exception as e:
            print(f"載入學生圖片 {result['id']}.png 時發生錯誤: {e}")

        rarity = result["rarity"]
        is_pickup = rarity.startswith("Pickup_")
        
        if rarity == "R":
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_1)
        elif rarity in ("SR", "Pickup_SR"):
            base_char_image.alpha_composite(YELLOW_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_2)
            if is_pickup:
                base_char_image.alpha_composite(PICKUP)
        elif rarity in ("SSR", "Pickup_SSR", "Pickup_Fes", "Limited_Other", "Fes_Other"):
            base_char_image.alpha_composite(PURPLE_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_3)
            if is_pickup:
                base_char_image.alpha_composite(PICKUP)
        
        return base_char_image

    def generate_gacha_image(self, results: list):
        """將多張角色頭像圖合成一張大的結果圖。"""
        char_images = [self.create_single_image(res) for res in results]
        
        image_count = len(char_images)
        cols = 5
        rows = math.ceil(image_count / cols)
        img_width, img_height = 120, 140
        padding = 10

        if image_count > 1:
            canvas_width = cols * img_width + padding * 2
            canvas_height = rows * img_height + padding * 2
            base_image = PIL.Image.new("RGBA", (canvas_width, canvas_height), (194, 229, 245, 255))
            for i, img in enumerate(char_images):
                x_offset = padding + (i % cols * img_width) + (img_width - 160) // 2
                y_offset = padding + (i // cols * img_height) + (img_height - 160) // 2
                base_image.alpha_composite(img, (x_offset, y_offset))
        elif image_count == 1:
            base_image = PIL.Image.new("RGBA", (200, 200), (194, 229, 245, 255)) 
            base_image.alpha_composite(char_images[0], ((200-160)//2, (200-160)//2))
        else:
            base_image = PIL.Image.new("RGBA", (200, 200), (194, 229, 245, 255))

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


class GachaDropdown(discord.ui.Select):
    def __init__(self, cog: Gacha, mode: str):
        self.cog = cog
        self.mode = mode
        
        options = []
        # 國際服卡池
        for i, banner in enumerate(self.cog.banners_gl):
            banner_name = self._get_banner_display_name(banner)
            options.append(discord.SelectOption(
                label=f"國際服：{banner_name}",
                value=f"global_{i}",
                description=banner["gachaType"]
            ))

        # 日服卡池
        for i, banner in enumerate(self.cog.banners_jp):
            banner_name = self._get_banner_display_name(banner)
            options.append(discord.SelectOption(
                label=f"日服：{banner_name}",
                value=f"japan_{i}",
                description=banner["gachaType"]
            ))

        if not options:
            options = [discord.SelectOption(label="暫無卡池", value="no_banner", disabled=True)]

        super().__init__(placeholder="選擇卡池", options=options)

    def _get_banner_display_name(self, banner):
        """根據卡池資訊生成顯示名稱"""
        if banner["gachaType"] == "NormalGacha":
            return "常駐招募"
        elif banner["rateups"]:
            pickup_names = [rateup["name"] for rateup in banner["rateups"]]
            return " & ".join(pickup_names[:2])  # 最多顯示兩個pickup角色名
        else:
            return "特殊招募"

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "no_banner":
            await interaction.response.send_message("目前沒有可用的卡池資訊。", ephemeral=True)
            return

        await interaction.response.defer()
        
        server_str, choice_str = self.values[0].split("_")
        choice = int(choice_str)

        if self.mode == "single":
            results = [self.cog.pull_logic(server_str, choice, False)]
        else:  # ten
            results = [self.cog.pull_logic(server_str, choice, i == 9) for i in range(10)]
        
        self.cog.generate_gacha_image(results)
        
        # 生成結果統計
        rarity_counts = {}
        for result in results:
            rarity = result["rarity"]
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
        
        # 生成embed
        banner_display_name = self._get_banner_display_name(
            (self.cog.banners_gl if server_str == "global" else self.cog.banners_jp)[choice]
        )
        
        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if server_str == 'global' else '日服'}\n**卡池：** {banner_display_name}",
            color=discord.Color.blue()
        )
        
        # 添加稀有度統計
        if len(results) > 1:
            stats_text = []
            for rarity, count in rarity_counts.items():
                rarity_display = {
                    "R": "⚪ R級",
                    "SR": "🟡 SR級", 
                    "Pickup_SR": "🟡 SR級 (UP)",
                    "SSR": "🟣 SSR級",
                    "Pickup_SSR": "🟣 SSR級 (UP)",
                    "Pickup_Fes": "🟣 SSR級 (Fes UP)",
                    "Limited_Other": "🟣 SSR級 (限定)",
                    "Fes_Other": "🟣 SSR級 (Fes)"
                }.get(rarity, rarity)
                stats_text.append(f"{rarity_display}: {count}")
            
            if stats_text:
                embed.add_field(name="📊 本次招募統計", value="\n".join(stats_text), inline=False)

        try:
            file = discord.File("result.png", filename="result.png")
            embed.set_image(url="attachment://result.png")
            view = GachaView(cog=self.cog, mode=self.mode, server=server_str, choice=choice, is_button=True)
            await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)
        except FileNotFoundError:
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，生成結果圖片時發生錯誤。", embed=embed)
        except Exception as e:
            print(f"傳送抽卡結果時發生錯誤: {e}")
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，處理您的請求時發生了未預期的錯誤。", embed=embed)


class GachaButton(discord.ui.Button):
    def __init__(self, cog: Gacha, mode: str, server: str, choice: int):
        super().__init__(label="再抽一次！", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.mode = mode
        self.server = server
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        if self.mode == "single":
            results = [self.cog.pull_logic(self.server, self.choice, False)]
        else:  # ten
            results = [self.cog.pull_logic(self.server, self.choice, i == 9) for i in range(10)]
            
        self.cog.generate_gacha_image(results)

        # Generating result statistics (same logic as dropdown)
        rarity_counts = {}
        for result in results:
            rarity = result["rarity"]
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1

        current_banner_list = self.cog.banners_gl if self.server == "global" else self.cog.banners_jp
        banner = current_banner_list[self.choice]
        
        banner_display_name = "常駐招募"
        if banner["gachaType"] != "NormalGacha" and banner["rateups"]:
            pickup_names = [rateup["name"] for rateup in banner["rateups"]]
            banner_display_name = " & ".join(pickup_names[:2])

        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if self.server == 'global' else '日服'}\n**卡池：** {banner_display_name}",
            color=discord.Color.blue()
        )
        
        # Add rarity statistics
        if len(results) > 1:
            stats_text = []
            for rarity, count in rarity_counts.items():
                rarity_display = {
                    "R": "⚪ R級",
                    "SR": "🟡 SR級", 
                    "Pickup_SR": "🟡 SR級 (UP)",
                    "SSR": "🟣 SSR級",
                    "Pickup_SSR": "🟣 SSR級 (UP)",
                    "Pickup_Fes": "🟣 SSR級 (Fes UP)",
                    "Limited_Other": "🟣 SSR級 (限定)",
                    "Fes_Other": "🟣 SSR級 (Fes)"
                }.get(rarity, rarity)
                stats_text.append(f"{rarity_display}: {count}")
            
            if stats_text:
                embed.add_field(name="📊 本次招募統計", value="\n".join(stats_text), inline=False)

        try:
            file = discord.File("result.png", filename="result.png")
            embed.set_image(url="attachment://result.png")
            view = GachaView(cog=self.cog, mode=self.mode, server=self.server, choice=self.choice, is_button=True)
            await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)


        except FileNotFoundError:
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，生成結果圖片時發生錯誤。", embed=embed)
        except Exception as e:
            print(f"傳送抽卡結果時發生錯誤: {e}")
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，處理您的請求時發生了未預期的錯誤。", embed=embed)


class GachaView(discord.ui.View):
    def __init__(self, cog: Gacha, mode: str, server: str = "global", choice: int = -1, is_button: bool = False):
        super().__init__(timeout=300) 
        self.cog = cog
        if is_button:
            self.add_item(GachaButton(self.cog, mode, server, choice))
        else:
            self.add_item(GachaDropdown(self.cog, mode))


async def setup(bot: commands.Bot):
    await bot.add_cog(Gacha(bot))
    print("Improved Gacha cog has been loaded with enhanced pull logic.")