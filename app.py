import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# 💡 절대 경로 지정을 통해 .env 파일을 찾지 못하는 버그를 방지합니다.
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

USERS_FILE = "users.json"
STOCKS_FILE = "stocks.json"
CONFIG_FILE = "config.json"
EVENTS_FILE = "events.json"

STOCK_RESET_RANGES = {
    "삼성전자": (10000, 1268090), "현대자동차": (100000, 1975238), "닌텐도": (150000, 600000),
    "패러독스 인터랙티브": (1000, 300000), "애플": (20000, 1500000), "삼성 SDI": (100000, 5000000),
    "LG전자": (5000, 1246490), "SK 하이닉스": (100000, 2385092), "S-oil": (10000, 700000),
    "엔비디아": (30000, 200000), "구글": (200000, 950000), "메타": (20000, 3000000),
    "인텔": (10000, 1800000), "한화": (1000, 948593), "다이소": (1000, 5000),
    "맥도날드": (10000, 1000000), 
    "로블록스": (1000, 300000), 
    "카카오": (10, 50000), # 10원부터 시작하는 눈물의 카카오
    "스페이스X": (50000, 800000)
}

market_status = {
    "is_open": False,
    "open_time": "09:00",
    "close_time": "22:30"
}

def load_data(file_path, default_value):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_value, f, ensure_ascii=False, indent=4)
        return default_value
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default_value

def save_data(file_path, data):
    temp_file = file_path + ".tmp"
    # 1. 먼저 임시 파일(.tmp)에 안전하게 쓰기
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    # 2. 쓰기가 완벽히 끝나면 원본 파일로 교체(Replace) - 원본 손상 방지
    os.replace(temp_file, file_path)

user_wallets = load_data(USERS_FILE, {})
stock_market = load_data(STOCKS_FILE, {})
config_data = load_data(CONFIG_FILE, {"news_channel_id": None})
events_pool = load_data(EVENTS_FILE, [])

def get_korea_time():
    return datetime.now(timezone.utc) + timedelta(hours=9)

def is_market_open_now():
    if not market_status["is_open"]:
        return False
    try:
        now_dt = get_korea_time()
        now_str = now_dt.strftime("%Y-%m-%d")
        open_dt = datetime.strptime(f"{now_str} {market_status['open_time']}", "%Y-%m-%d %H:%M")
        close_dt = datetime.strptime(f"{now_str} {market_status['close_time']}", "%Y-%m-%d %H:%M")
        return open_dt <= now_dt.replace(tzinfo=None) <= close_dt
    except Exception:
        return market_status["is_open"]

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)}개의 슬래시 명령어 동기화 완료.")
    except Exception as e:
        print(f"❌ 명령어 동기화 실패: {e}")
    if not stock_price_loop.is_running():
        stock_price_loop.start()

@tasks.loop(hours=1)
async def stock_price_loop():
    global stock_data
    stock_data = load_data(STOCKS_FILE, {})
    if not stock_data:
        return

    # 💡 5% 확률로 자동으로 시장 뉴스(이벤트)가 터지던 로직을 완전히 제거했습니다.
    current_event = None

    for name, info in stock_data.items():
        current_price = info["price"]
        
        # ⭐ [선물거래용] 주가 변동 직전의 진짜 가격을 기록해 둡니다.
        info["old_price_for_futures"] = current_price
        
        start_price = info.get("start_price", current_price)

        change_percent = random.uniform(-4.5, 4.5)
        if current_price < 5000:
            change_percent += random.uniform(-2.0, 2.0)

        trend = info.get("trend", 0)
        change_percent += trend
        if random.random() < 0.15:
            info["trend"] = random.uniform(-1.5, 1.5)

        price_change = int(current_price * (change_percent / 100))
        current_price += price_change
        current_price = max(10, min(current_price, 2000000000))

        rate = ((current_price - start_price) / start_price) * 100
        info["price"] = current_price
        info["rate"] = round(rate, 2)
        info["change"] = current_price - start_price

    save_data(STOCKS_FILE, stock_data)

    await check_futures_results()

@bot.command(name="시간수정")
@commands.has_permissions(administrator=True)
async def change_stock_loop_time(ctx, minutes: int):
    if minutes <= 0: return
    try: await ctx.message.delete()
    except discord.Forbidden: pass
    config_data["update_interval_minutes"] = minutes
    save_data(CONFIG_FILE, config_data)
    stock_price_loop.change_interval(minutes=minutes)
    await ctx.send(f"⏰ 주가 변동 주기가 **{minutes}분**으로 변경되었습니다. (이 메시지는 잠시 후 사라집니다.)", delete_after=5)

@bot.command(name="주가수정")
@commands.has_permissions(administrator=True)
async def modify_stock_price(ctx, name: str, amount: int):
    try: await ctx.message.delete()
    except discord.Forbidden: pass
    global stock_data; stock_data = load_data(STOCKS_FILE, {})
    if name not in stock_data:
        await ctx.send(f"❌ '{name}'은(는) 존재하지 않는 기업입니다.", delete_after=5)
        return
    old_price = stock_data[name]["price"]; new_price = max(100, old_price + amount)
    stock_data[name]["price"] = new_price; stock_data[name]["change"] = new_price - old_price
    stock_data[name]["rate"] = ((new_price - old_price) / old_price) * 100 if old_price > 0 else 0.0
    save_data(STOCKS_FILE, stock_data)
    status_text = f"📈 {amount:,}원 상승" if amount > 0 else (f"📉 {abs(amount):,}원 하락" if amount < 0 else "⚪ 보합")
    await ctx.send(f"펌핑 완료 🛑 **{name}** 주가 강제 조정\n└ 이전가: `{old_price:,}원` ➡️ 변경가: `{new_price:,}원` ({status_text})", delete_after=5)

@bot.command(name="event")
@commands.has_permissions(administrator=True)  # 관리자 권한 필수
async def check_event(ctx, event_id: str = None):
    # json 파일 로드
    events_data = load_data(EVENTS_FILE, {})

    # 1. !event 만 입력한 경우 -> 관리자 개인 DM으로 뉴스 ID 목록 발송
    if event_id is None:
        if not events_data:
            await ctx.send("📰 현재 `events.json`에 등록된 뉴스가 없습니다.")
            return

        embed = discord.Embed(
            title="🕵️ 관리자 전용 비밀 뉴스 ID 목록",
            description="조회하려는 뉴스의 ID를 확인하고 서버에서 `!event (뉴스ID)`를 입력하세요.\n*※ 이 메시지는 관리자님에게만 개인 DM으로 발송되었습니다.*",
            color=discord.Color.dark_purple()
        )
        
        for e_id, info in events_data.items():
            news_title = info.get("title", "제목 없음")
            embed.add_field(name=f"🆔 {e_id}", value=f"┗ 제목: {news_title}", inline=False)
        
        # 관리자 DM으로 전송 시도
        try:
            await ctx.author.send(embed=embed)
            # 채널에는 유저들이 눈치채지 못하게 안내 메시지만 살짝 남기거나, 원하시면 이 안내도 지우셔도 됩니다.
            await ctx.send("🔒 뉴스 ID 목록을 관리자님의 개인 DM으로 안전하게 발송했습니다.", delete_after=5)
        except discord.Forbidden:
            # 관리자가 DM 수신 거부를 해둔 경우 경고
            await ctx.send("❌ 관리자님의 'DM 수신 설정'이 차단되어 있어 목록을 보낼 수 없습니다. 설정을 확인해 주세요.")
        
        return

    # 2. !event (뉴스 ID)를 입력한 경우 -> 변동률 100% 노출 및 명령어 삭제
    if event_id not in events_data:
        await ctx.send(f"❌ `{event_id}`은(는) 존재하지 않는 뉴스 ID입니다.")
        return

    # 관리자가 입력한 명령어 텍스트 즉시 삭제 (비밀 유지)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    except discord.HTTPException:
        pass

    event_info = events_data[event_id]
    news_title = event_info.get("title", "제목 없음")
    news_text = event_info.get("text", "내용 없음")
    change_rate = event_info.get("change", "0")

    # 🎯 변동률 100% 정확하게 분석하여 노출
    try:
        rate_val = float(change_rate)
        if rate_val > 0:
            rate_str = f"📈 +{change_rate}% (상승 유도)"
        elif rate_val < 0:
            rate_str = f"📉 {change_rate}% (하락 유도)"
        else:
            rate_str = f"變 {change_rate}% (변동 없음)"
    except ValueError:
        rate_str = f"❓ {change_rate} (수치 데이터 오류)"

    embed = discord.Embed(
        title=f"🕵️ 관리자 비밀 뉴스 조회 (ID: {event_id})",
        description=f"**제목: {news_title}**\n*조회 완료 후 관리자의 명령어는 자동으로 삭제되었습니다.*",
        color=discord.Color.dark_purple()
    )
    embed.add_field(name="💬 뉴스 헤드라인 내용", value=f"\"{news_text}\"", inline=False)
    embed.add_field(name="📊 예측 변동률 (보안 등급: 🌟🌟🌟)", value=rate_str, inline=False)
    embed.set_footer(text=f"요청자: {ctx.author.display_name} | 분석 신뢰도: 100%")

    # 명령어 입력 채널에 상세 정보 출력 (명령어 친 흔적은 지워졌으므로 유저들은 결과만 보게 됨)
    # 완전한 비밀을 원하시면 이 임베드마저도 ctx.author.send(embed=embed)로 바꾸어 DM으로 받으셔도 됩니다!
    await ctx.send(embed=embed)

@check_event.error
async def check_event_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 권한이 없습니다.")

@bot.tree.command(name="주식시작", description="주식 게임에 가입하고 투자 자금을 받습니다.")
async def start_game(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in user_wallets:
        await interaction.response.send_message("❌ 이미 주식 게임에 가입되어 있습니다.", ephemeral=True)
        return

    # 💡 [역할 관리 권한 부족 예외 처리 보완]
    role = interaction.guild.get_role(1504759968837140491)
    if role:
        try:
            await interaction.user.add_roles(role)
        except discord.Forbidden:
            print("⚠️ 경고: 봇의 역할 순서가 지급할 역할보다 낮아 역할을 지급하지 못했습니다.")
            # 역할을 못 주더라도 가입 프로세스는 계속 진행되도록 처리하거나 안내창을 띄웁니다.

    user_wallets[user_id] = {"money": 500000, "debt": 0, "bank": "None", "stocks": {}, "last_attendance": ""}
    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message("🎉 가입 완료! 초기 자본 500,000원이 지급되었습니다.")

@bot.tree.command(name="주가보기", description="현재 주식 시장의 주가를 확인합니다. (나에게만 보임)")
async def show_stocks(interaction: discord.Interaction):
    global stock_data; stock_data = load_data(STOCKS_FILE, {})
    embed = discord.Embed(title="📈 현재 주식 시장 시세표", description="현재 거래 가능한 가상 주식 목록입니다.\n━━━━━━━━━━━━━━━━━━━━━━━━", color=discord.Color.green())
    for name, info in stock_data.items():
        price = info.get("price", 0); rate = info.get("rate", 0.0); change = info.get("change", 0)
        if change > 0: box_content = f"현재가: {price:,}원\n+ 변동폭: 🟥 +{rate:.2f}% (+{int(change):,}원)"
        elif change < 0: box_content = f"현재가: {price:,}원\n- 변동폭: 🟦 {rate:.2f}% ({int(change):,}원)"
        else: box_content = f"현재가: {price:,}원\n  변동폭: ⚪ 0.00% (0원)"
        embed.add_field(name=f"🏢 {name}", value=f"```diff\n{box_content}\n```", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


class FuturesStockSelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [
            discord.SelectOption(label=name, description=f"현재가: {info['price']:,}원", value=name) 
            for name, info in stocks_data.items()
        ]
        super().__init__(placeholder="선물 계약을 맺을 기업을 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(
            content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n이제 아래에서 투자 방향(롱/숏)과 레버리지 배율을 설정하세요!", 
            embed=None
        )
        
# ==========================================================
# 🎰 [선물 거래] 유저 선택용 드롭다운 메뉴 클래스
# ==========================================================
class FuturesStockSelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [
            discord.SelectOption(label=name, description=f"현재가: {info['price']:,}원", value=name) 
            for name, info in stocks_data.items()
        ]
        super().__init__(placeholder="선물 계약을 맺을 기업을 선택하세요...", min_values=1, max_values=1, options=options)
        
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(
            content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n이제 아래에서 투자 방향(롱/숏)과 레버리지 배율을 설정하세요!", 
            embed=None
        )


# ==========================================================
# 🎰 [선물 거래] 메인 뷰 클래스 (중복 배팅 방지 락 장치)
# ==========================================================
class FuturesView(discord.ui.View):
    def __init__(self, stocks_data, user_money, has_active_contract=False):
        super().__init__(timeout=60)
        self.selected_stock = None
        self.user_money = user_money
        self.position = None  # "LONG" 또는 "SHORT"
        self.leverage = 1
        self.has_active_contract = has_active_contract

        # 💡 이미 계약을 진행 중(도박 시작함)이라면 드롭다운 메뉴를 추가하지 않습니다.
        if not has_active_contract:
            self.add_item(FuturesStockSelect(stocks_data))

    @discord.ui.button(label="📈 LONG (오른다)", style=discord.ButtonStyle.success, row=1)
    async def set_long(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.has_active_contract:
            return await interaction.response.send_message("❌ 이미 진행 중인 선물 계약이 존재합니다.", ephemeral=True)
        self.position = "LONG"
        await interaction.response.send_message("방향이 **📈 LONG (상승)**으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="📉 SHORT (떨어진다)", style=discord.ButtonStyle.danger, row=1)
    async def set_short(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.has_active_contract:
            return await interaction.response.send_message("❌ 이미 진행 중인 선물 계약이 존재합니다.", ephemeral=True)
        self.position = "SHORT"
        await interaction.response.send_message("방향이 **📉 SHORT (하락)**으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="🚀 배율: 1배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_1(self, interaction: discord.Interaction, button: discord.ui.Button): 
        if self.has_active_contract: return await interaction.response.send_message("❌ 이미 계약이 존재합니다.", ephemeral=True)
        self.leverage = 1; await interaction.response.send_message("레버리지가 **1배**로 설정되었습니다.", ephemeral=True)
        
    @discord.ui.button(label="🔥 배율: 3배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_3(self, interaction: discord.Interaction, button: discord.ui.Button): 
        if self.has_active_contract: return await interaction.response.send_message("❌ 이미 계약이 존재합니다.", ephemeral=True)
        self.leverage = 3; await interaction.response.send_message("레버리지가 **3배(고위험)**로 설정되었습니다.", ephemeral=True)
        
    @discord.ui.button(label="💀 배율: 5배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_5(self, interaction: discord.Interaction, button: discord.ui.Button): 
        if self.has_active_contract: return await interaction.response.send_message("❌ 이미 계약이 존재합니다.", ephemeral=True)
        self.leverage = 5; await interaction.response.send_message("레버리지가 **5배(지옥길)**로 설정되었습니다.", ephemeral=True)

class FuturesBetModal(discord.ui.Modal, title="💰 선물 계약 투자금 입력"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.money_input = discord.ui.TextInput(label="투자할 현금 액수", placeholder="숫자만 입력 (예: 50000)", min_length=1, max_length=15, required=True)
        self.add_item(self.money_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.view.selected_stock or not self.view.position:
            return await interaction.response.send_message("❌ 종목 선택 및 롱/숏 방향 설정을 먼저 완료해 주세요.", ephemeral=True)
        
        try:
            bet_amount = int(self.money_input.value)
        except ValueError:
            return await interaction.response.send_message("❌ 숫자만 입력 가능합니다.", ephemeral=True)

        if bet_amount <= 0:
            return await interaction.response.send_message("❌ 최소 1원 이상 투자해야 합니다.", ephemeral=True)
        if bet_amount > self.view.user_money:
            return await interaction.response.send_message("❌ 보유하신 소지금이 부족합니다.", ephemeral=True)

        user_id = str(interaction.user.id)
        global user_wallets
        user_wallets = load_data(USERS_FILE, {})

        user_wallets[user_id]["money"] -= bet_amount
        
        if "futures" not in user_wallets[user_id]:
            user_wallets[user_id]["futures"] = []
            
        contract = {
            "stock_name": self.view.selected_stock,
            "position": self.view.position,
            "leverage": self.view.leverage,
            "bet_money": bet_amount
        }
        user_wallets[user_id]["futures"].append(contract)
        save_data(USERS_FILE, user_wallets)

        embed = discord.Embed(title="🎲 선물 계약 체결 완료 (대기 중)", color=discord.Color.dark_orange())
        embed.description = f"다음 주가 변동 주기(30분 간격)에 결과가 정산됩니다."
        embed.add_field(name="🏢 종목", value=self.view.selected_stock, inline=True)
        embed.add_field(name="📊 포지션", value="📈 LONG" if self.view.position == "LONG" else "📉 SHORT", inline=True)
        embed.add_field(name="🔥 레버리지", value=f"{self.view.leverage}배", inline=True)
        embed.add_field(name="💸 투자금", value=f"{bet_amount:,}원", inline=False)
        
        await interaction.response.edit_message(content=None, embed=embed, view=None)

# ==========================================================
# 🎰 [선물 거래] /도박 통합 슬래시 명령어
# ==========================================================
@bot.tree.command(name="도박", description="주가의 상승/하락에 배팅하는 레버리지 배팅을 진행합니다. (나에게만 보임)")
async def futures_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_wallets = load_data(USERS_FILE, {})
    current_stocks = load_data(STOCKS_FILE, {})
    
    if user_id not in user_wallets:
        return await interaction.response.send_message("❌ 가입이 필요합니다. 먼저 주식을 시작해 주세요!", ephemeral=True)
    if not current_stocks:
        return await interaction.response.send_message("❌ 상장된 기업이 없습니다.", ephemeral=True)
        
    user_money = user_wallets[user_id].get("money", 0)
    user_contracts = user_wallets[user_id].get("futures", [])
    
    # 💡 유저가 이미 도박 계약을 가지고 있는지 판단 (True / False)
    has_active = len(user_contracts) > 0
    
    # 생성자에 True/False 여부를 명확하게 전달합니다.
    view = FuturesView(current_stocks, user_money, has_active_contract=has_active)
    
    embed = discord.Embed(title="📉 가상 주식 마진/선물 거래소 📈")
    
    if has_active:
        # 🟢 도박을 이미 시작한 유저인 경우 ➡️ "먼저 도박을 시작하세요!" 대신 상황에 맞춘 안내문 출력
        embed.description = "📊 **알림**: 현재 아직 정산되지 않은 선물 계약(도박)이 존재합니다!\n" \
                            "다음 주가 변동 주기(30분 간격)에 시스템이 결과를 자동으로 정산해 줄 때까지 기다려 주세요."
        embed.color = discord.Color.dark_grey()
        # 이미 도박 중일 땐 하단의 [투자금 입력 및 계약 완료] 버튼을 아예 붙이지 않습니다.
    else:
        # 🔴 도박을 아직 안 한 유저인 경우 ➡️ 정상적인 베팅 UI 활성화
        embed.description = "⚠️ **주의**: 예측 실패 시 원금이 통째로 청산(소각)당할 수 있는 위험한 투자입니다.\n\n" \
                            "1️⃣ 드롭다운에서 기업을 고르세요.\n" \
                            "2️⃣ 롱(오른다) 또는 숏(떨어진다) 버튼을 누르세요.\n" \
                            "3️⃣ 배율을 선택하고 최종 [계약 완료] 버튼을 누르세요."
        embed.color = discord.Color.dark_red()
        
        # 도박이 없을 때만 최종 배팅을 완료할 수 있는 버튼을 장착해 줍니다.
        confirm_button = discord.ui.Button(label="💳 투자금 입력 및 계약 완료", style=discord.ButtonStyle.primary, row=4)
        async def confirm_callback(interact):
            await interact.response.send_modal(FuturesBetModal(view))
        confirm_button.callback = confirm_callback
        view.add_item(confirm_button)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def check_futures_results():
    global user_wallets
    user_wallets = load_data(USERS_FILE, {})
    stock_data = load_data(STOCKS_FILE, {})
    
    # 💡 config.json 파일을 실시간으로 안전하게 로드하여 채널 누락을 방지합니다.
    current_config = load_data(CONFIG_FILE, {})
    
    for user_id, info in list(user_wallets.items()):
        contracts = info.get("futures", [])
        if not contracts:
            continue
            
        retained_contracts = []
        total_payout = 0
        summary_messages = []

        for c in contracts:
            s_name = c["stock_name"]
            pos = c["position"]
            lev = c["leverage"]
            bet = c["bet_money"]
            
            old_p = stock_data.get(s_name, {}).get("old_price_for_futures", 0)
            new_p = stock_data.get(s_name, {}).get("price", 0)
            
            if old_p == 0 or old_p == new_p:
                retained_contracts.append(c)
                continue
                
            raw_rate = ((new_p - old_p) / old_p)
            
            if pos == "LONG":
                earning_rate = raw_rate * lev
            else:
                earning_rate = -raw_rate * lev
                
            if earning_rate <= -1.0:
                summary_messages.append(f"💀 **{s_name}** ({pos} {lev}배) ➡️ 주가 반대 급변으로 **[청산]**되어 `{bet:,}원`이 전액 소각되었습니다.")
            else:
                payout = int(bet + (bet * earning_rate))
                total_payout += payout
                profit = payout - bet
                sign = "🟢 +" if profit >= 0 else "🔴 "
                summary_messages.append(f"💰 **{s_name}** ({pos} {lev}배) ➡️ 정산 금액: `{payout:,}원` (수익: {sign}{profit:,}원)")

        user_wallets[user_id]["money"] += total_payout
        user_wallets[user_id]["futures"] = retained_contracts
        save_data(USERS_FILE, user_wallets)
        
        # 🔔 정산 리포트 알림 처리 구역
        if summary_messages:
            embed = discord.Embed(title="🎰 가상 주식 선물 거래 정산 리포트", color=discord.Color.orange())
            embed.description = "\n".join(summary_messages)
            
            user = bot.get_user(int(user_id))
            if not user:
                try: 
                    user = await bot.fetch_user(int(user_id))
                except Exception: 
                    user = None

            if user:
                try:
                    await user.send(embed=embed)
                    continue # 🎯 DM 전송에 성공하면 아래 서버용 우회 코드를 실행하지 않고 다음 유저로 패스
                except discord.Forbidden:
                    pass # DM이 차단되어 있다면 하단의 서버 채널 발송 로직으로 진입합니다.
            
            # 💡 수정된 뉴스 채널 조회 및 강제 안전 발송 로직
            try:
                channel_id = current_config.get("news_channel_id")
                if channel_id:
                    target_channel = bot.get_channel(int(channel_id))
                    if not target_channel:
                        target_channel = await bot.fetch_channel(int(channel_id))
                    
                    if target_channel:
                        warning_msg = f"⚠️ <@{user_id}>님, 봇의 **[서버 멤버 DM 허용]** 설정이 꺼져 있어 정산 결과를 DM으로 보내지 못했습니다! 설정을 켜주세요."
                        await target_channel.send(content=warning_msg, embed=embed)
                    else:
                        print(f"❌ [선물 알림 오류] ID {channel_id} 채널을 디스코드에서 찾을 수 없습니다.")
                else:
                    print("❌ [선물 알림 오류] config.json에 'news_channel_id' 설정이 누락되었습니다.")
            except Exception as e:
                print(f"❌ [선물 알림 오류] 서버 채널 송출 중 예외 발생: {e}")

class StockBuySelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [
            discord.SelectOption(label=name, description=f"현재 1주당 가격: {info['price']:,}원", value=name) 
            for name, info in stocks_data.items()
        ]
        super().__init__(placeholder="매수할 기업을 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(
            content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n아래에서 구매할 주식 수량 버튼을 클릭하세요!", 
            embed=None
        )

class StockBuyView(discord.ui.View):
    def __init__(self, stocks_data):
        super().__init__(timeout=60)
        self.add_item(StockBuySelect(stocks_data))
        self.selected_stock = None

    @discord.ui.button(label="1주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_1(self, interaction: discord.Interaction, button: discord.ui.Button): 
        await self.process_purchase(interaction, 1)

    @discord.ui.button(label="2주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_2(self, interaction: discord.Interaction, button: discord.ui.Button): 
        await self.process_purchase(interaction, 2)

    @discord.ui.button(label="5주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_5(self, interaction: discord.Interaction, button: discord.ui.Button): 
        await self.process_purchase(interaction, 5)

    @discord.ui.button(label="10주 구매", style=discord.ButtonStyle.primary, row=2)
    async def buy_10(self, interaction: discord.Interaction, button: discord.ui.Button): 
        await self.process_purchase(interaction, 10)

    @discord.ui.button(label="20주 구매", style=discord.ButtonStyle.primary, row=2)
    async def buy_20(self, interaction: discord.Interaction, button: discord.ui.Button): 
        await self.process_purchase(interaction, 20)

    async def process_purchase(self, interaction: discord.Interaction, amount: int):
        if not self.selected_stock: 
            return await interaction.response.send_message("❌ 기업을 먼저 고르세요.", ephemeral=True)
            
        user_id = str(interaction.user.id)
        global user_wallets, stock_data
        user_wallets = load_data(USERS_FILE, {})
        stock_data = load_data(STOCKS_FILE, {})
        
        if user_id not in user_wallets: 
            return await interaction.response.send_message("❌ `/주식시작`을 먼저 진행해 주세요.", ephemeral=True)
            
        current_price = stock_data[self.selected_stock]["price"]
        total_cost = current_price * amount
        user_money = user_wallets[user_id].get("money", 0)
        
        if user_money < total_cost: 
            return await interaction.response.send_message("❌ 잔액이 부족합니다.", ephemeral=True)
            
        if "stocks" not in user_wallets[user_id]: 
            user_wallets[user_id]["stocks"] = {}
            
        user_wallets[user_id]["stocks"][self.selected_stock] = user_wallets[user_id]["stocks"].get(self.selected_stock, 0) + amount
        user_wallets[user_id]["money"] -= total_cost
        save_data(USERS_FILE, user_wallets)
        
        embed = discord.Embed(title="📥 주식 매수 체결 완료", color=discord.Color.blue())
        embed.add_field(name="🏢 종목명", value=self.selected_stock, inline=True)
        embed.add_field(name="📊 체결 수량", value=f"{amount} 주", inline=True)
        embed.add_field(name="💸 총 결제 금액", value=f"**{total_cost:,} 원**", inline=False)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

@bot.tree.command(name="주식구매", description="상장된 주식을 선택하고 원하는 수량만큼 구매합니다. (나에게만 보임)")
async def buy_stock_command(interaction: discord.Interaction):
    current_stocks = load_data(STOCKS_FILE, {})
    if not current_stocks: return await interaction.response.send_message("❌ 상장된 기업이 없습니다.", ephemeral=True)
    await interaction.response.send_message(content="🛒 **가상 주식 매수 시스템**\n드롭다운에서 기업을 선택해 주세요!", view=StockBuyView(current_stocks), ephemeral=True)

class StockSellSelect(discord.ui.Select):
    def __init__(self, stocks_data, user_owned_stocks):
        # 유저가 보유 중인 주식만 드롭다운 메뉴 옵션으로 노출합니다.
        options = []
        for name in user_owned_stocks.keys():
            if name in stocks_data:
                amount = user_owned_stocks[name]
                if amount > 0:
                    options.append(
                        discord.SelectOption(
                            label=name, 
                            description=f"보유량: {amount}주 | 현재가: {stocks_data[name]['price']:,}원", 
                            value=name
                        )
                    )
        
        if not options:
            options.append(discord.SelectOption(label="보유 주식 없음", description="판매 가능한 주식이 없습니다.", value="none"))
            
        super().__init__(placeholder="매도할 주식을 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ 보유 중인 주식이 없어 선택할 수 없습니다.", ephemeral=True)
            
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(
            content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n아래에서 판매할 주식 수량 버튼을 클릭하세요!", 
            embed=None
        )

class StockSellView(discord.ui.View):
    def __init__(self, stocks_data, user_owned_stocks):
        super().__init__(timeout=60)
        self.add_item(StockSellSelect(stocks_data, user_owned_stocks))
        self.selected_stock = None

    @discord.ui.button(label="1주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_1(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sale(interaction, 1)
    @discord.ui.button(label="2주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_2(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sale(interaction, 2)
    @discord.ui.button(label="5주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_5(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sale(interaction, 5)
    @discord.ui.button(label="10주 판매", style=discord.ButtonStyle.primary, row=2)
    async def sell_10(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sale(interaction, 10)
    @discord.ui.button(label="20주 판매", style=discord.ButtonStyle.primary, row=2)
    async def sell_20(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sale(interaction, 20)

    async def process_sale(self, interaction: discord.Interaction, amount: int):
        if not self.selected_stock: 
            return await interaction.response.send_message("❌ 기업을 먼저 고르세요.", ephemeral=True)
            
        user_id = str(interaction.user.id)
        global user_wallets, stock_data
        user_wallets = load_data(USERS_FILE, {})
        stock_data = load_data(STOCKS_FILE, {})
        
        if user_id not in user_wallets or "stocks" not in user_wallets[user_id]:
            return await interaction.response.send_message("❌ 보유 자산이 없습니다.", ephemeral=True)
            
        owned_amount = user_wallets[user_id]["stocks"].get(self.selected_stock, 0)
        if owned_amount < amount:
            return await interaction.response.send_message(f"❌ 주식이 부족합니다. (현재 보유: {owned_amount}주)", ephemeral=True)
            
        current_price = stock_data[self.selected_stock]["price"]
        total_revenue = current_price * amount
        
        user_wallets[user_id]["stocks"][self.selected_stock] -= amount
        user_wallets[user_id]["money"] += total_revenue
        
        # 0주가 된 주식은 깔끔하게 삭제
        if user_wallets[user_id]["stocks"][self.selected_stock] <= 0:
            del user_wallets[user_id]["stocks"][self.selected_stock]
            
        save_data(USERS_FILE, user_wallets)
        
        embed = discord.Embed(title="📤 주식 매도 체결 완료", color=discord.Color.red())
        embed.add_field(name="🏢 종목명", value=self.selected_stock, inline=True)
        embed.add_field(name="📊 체결 수량", value=f"{amount} 주", inline=True)
        embed.add_field(name="💰 총 정산 금액", value=f"**+{total_revenue:,} 원**", inline=False)
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        
@bot.tree.command(name="주식매도", description="보유 중인 주식을 시장에 판매하여 현금화합니다. (나에게만 보임)")
async def sell_stock_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id); current_stocks = load_data(STOCKS_FILE, {}); user_wallets = load_data(USERS_FILE, {})
    if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
    user_owned_stocks = user_wallets[user_id].get("stocks", {})
    await interaction.response.send_message(content="📤 **가상 주식 매도 시스템**\n판매할 주식을 선택해 주세요!", view=StockSellView(current_stocks, user_owned_stocks), ephemeral=True)

@bot.tree.command(name="자산", description="내 소지금, 보유 중인 주식 현황, 빚 등을 모두 확인합니다. (나에게만 보임)")
async def show_my_assets(interaction: discord.Interaction):
    user_id = str(interaction.user.id); global user_wallets, stock_data
    user_wallets = load_data(USERS_FILE, {}); stock_data = load_data(STOCKS_FILE, {})
    if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
    user_info = user_wallets[user_id]; cash = user_info.get("money", 0); debt = user_info.get("debt", 0); my_stocks = user_info.get("stocks", {})
    total_stock_value = 0; stock_list_string = ""
    if my_stocks:
        for stock_name, owned_amount in my_stocks.items():
            if owned_amount <= 0: continue
            current_unit_price = stock_data.get(stock_name, {}).get("price", 0); sub_total_value = current_unit_price * owned_amount
            total_stock_value += sub_total_value; stock_list_string += f"🔹 **{stock_name}** : `{owned_amount:,}주` (총 {sub_total_value:,}원 상당)\n"
    stock_list_text = "```현재 보유 중인 주식이 없습니다.\n```" if not stock_list_string else stock_list_string
    net_worth = cash + total_stock_value - debt
    embed = discord.Embed(title=f"💳 {interaction.user.name}님의 자산 보고서", description=f"현재 시각 시세를 기준으로 측정된 실시간 자산 현황입니다.", color=discord.Color.purple())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="💰 보유 현금 (소지금)", value=f"`{cash:,} 원`", inline=True)
    embed.add_field(name="📉 남은 은행 빚", value=f"`{debt:,} 원`" if debt > 0 else "`0 원 (클린)`", inline=True)
    embed.add_field(name="📈 총 주식 평가액", value=f"`{total_stock_value:,} 원`", inline=True)
    embed.add_field(name="📋 상세 주식 보유 리스트", value=stock_list_text, inline=False)
    embed.add_field(name="📊 실질 순자산 (현금 + 주식 - 빚)", value=f"==> **{net_worth:,} 원**", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="주식초기화", description="모든 참가자의 자산을 초기화하고 주가를 랜덤으로 갱신합니다. (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_stock_game(interaction: discord.Interaction):
    global user_wallets, stock_data
    user_wallets = load_data(USERS_FILE, {})
    for user_id in user_wallets.keys(): user_wallets[user_id] = {"money": 500000, "debt": 0, "bank": "None", "stocks": {}, "last_attendance": ""}
    save_data(USERS_FILE, user_wallets)
    stock_data = load_data(STOCKS_FILE, {})
    for name, range_values in STOCK_RESET_RANGES.items():
        if name in stock_data:
            min_p, max_p = range_values
            stock_data[name]["price"] = random.randint(min_p // 100, max_p // 100) * 100
            stock_data[name]["rate"] = 0.0; stock_data[name]["change"] = 0
    save_data(STOCKS_FILE, stock_data)
    await interaction.response.send_message("🔄 주식 시장 대초기화가 완료되었습니다!")
    
@bot.tree.command(name="뉴스", description="[관리자 전용] 랜덤으로 2개의 뉴스를 발생시키고 주가에 즉시 반영합니다.")
async def trigger_random_news(interaction: discord.Interaction):
    # 1. 관리자 권한 체크
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 이 명령어는 서버 관리자만 사용할 수 있습니다.", ephemeral=True)
        return

    # 2. 파일 데이터 로드
    events_data = load_data(EVENTS_FILE, {})
    stocks_data = load_data(STOCKS_FILE, {})

    # 등록된 뉴스가 2개 미만인 경우 예외 처리
    if len(events_data) < 2:
        await interaction.response.send_message("❌ `events.json`에 등록된 뉴스가 최소 2개 이상이어야 합니다.", ephemeral=True)
        return

    # 3. 전체 뉴스 중 랜덤으로 2개 선택 (중복 없이)
    selected_ids = random.sample(list(events_data.keys()), 2)

    # 뉴스 결과를 담을 임베드 생성
    embed = discord.Embed(
        title="🚨 [긴급 속보] 주식 시장 주요 뉴스 발행",
        description="관리자에 의해 새로운 뉴스가 발생하여 시장 주가에 즉시 반영되었습니다.",
        color=discord.Color.red()
    )

    # 4. 선택된 2개의 뉴스를 순회하며 주가 반영 및 임ベ드 추가
    for event_id in selected_ids:
        event_info = events_data[event_id]
        news_title = event_info.get("title", "제목 없음")
        news_text = event_info.get("text", "내용 없음")
        change_rate = event_info.get("change", "0")

        # 뉴스 ID 앞부분을 추출하여 실제 stocks.json의 기업 명칭과 매칭
        # (알려주신 맵핑 규칙 적용)
        prefix = event_id.split('.')[0].lower()
        
        if "apple" in prefix:
            target_company = "애플"
        elif "samsung" in prefix:
            target_company = "삼성전자"
        elif "hanhwa" in prefix:
            target_company = "한화"
        else:
            # 지정된 3개 기업 외에 다른 이름이 들어올 경우를 대비한 자동 매칭 예외처리
            target_company = None
            for stock_name in stocks_data.keys():
                if prefix in stock_name.lower() or stock_name.lower() in prefix:
                    target_company = stock_name
                    break

        # stocks.json에 해당 기업이 존재하는지 확인 후 주가 변동 적용
        if target_company and target_company in stocks_data:
            try:
                rate = float(change_rate) / 100.0
                current_price = stocks_data[target_company]["price"]
                
                # 새로운 주가 계산 (소수점 버림)
                new_price = math.floor(current_price * (1 + rate))
                stocks_data[target_company]["price"] = new_price
                
                # 부호 및 화살표 표시
                arrow = f"📈 +{change_rate}%" if rate > 0 else f"📉 {change_rate}%"
                
                # 임베드에 뉴스 정보 추가
                embed.add_field(
                    name=f"📌 {news_title}",
                    value=f"{news_text}\n\n🏢 **영향 기업:** {target_company}\n📊 **주가 변동:** {current_price:,}원 ➡️ **{new_price:,}원** ({arrow})",
                    inline=False
                )
            except ValueError:
                print(f"❌ 뉴스 수치 변환 오류 (ID: {event_id})")
        else:
            # 기업 매칭에 실패한 경우 뉴스는 띄우되 주가는 바꾸지 않음
            embed.add_field(
                name=f"📌 {news_title} (시장 영향 없음)",
                value=f"{news_text}",
                inline=False
            )

    # 5. 변동된 주가 데이터를 `stocks.json`에 즉시 저장!
    save_data(STOCKS_FILE, stocks_data)

    # 6. 전 서버 유저들이 볼 수 있게 속보 전송 (ephemeral=False)
    await interaction.response.send_message(embed=embed, ephemeral=False)

class StockDescriptionSelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = []
        for name, info in stocks_data.items():
            options.append(
                discord.SelectOption(
                    label=name, 
                    description=f"현재가: {info.get('price', 0):,}원", 
                    value=name
                )
            )
        super().__init__(
            placeholder="🏢 설명을 보고 싶은 기업을 선택하세요...", 
            min_values=1, 
            max_values=1, 
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_stock = self.values[0]
        
        global STOCKS_FILE
        # 💡 한글 깨짐으로 인한 매칭 실패를 막기 위해 utf-8 인코딩을 강제로 지정하여 파일을 읽습니다.
        try:
            with open(STOCKS_FILE, "r", encoding="utf-8") as f:
                current_stocks = json.load(f)
        except Exception:
            current_stocks = {}
        
        if not current_stocks or selected_stock not in current_stocks:
            await interaction.response.send_message("❌ 존재하지 않거나 상장 폐지된 기업입니다.", ephemeral=True)
            return

        target_info = current_stocks[selected_stock]
        
        # 🎯 실제 json 구조의 "description"을 완벽하게 조준합니다.
        desc = target_info.get("description", "등록된 설명이 없는 기업입니다.")
        price = target_info.get("price", 0)

        embed = discord.Embed(
            title=f"🏢 {selected_stock} 기업 정보 도감",
            description=f"\n{desc}\n",
            color=discord.Color.blue()
        )
        embed.add_field(name="💵 현재 주가", value=f"`{price:,}원`", inline=True)
        embed.set_footer(text=f"조회자: {interaction.user.display_name}")

        # 드롭다운 메시지를 결과 화면으로 전환
        await interaction.response.edit_message(embed=embed, view=None)


class StockDescriptionView(discord.ui.View):
    def __init__(self, stocks_data):
        super().__init__(timeout=60)
        self.add_item(StockDescriptionSelect(stocks_data))


# ⚠️ 주의: 이 명령어 선언은 app.py 전체에서 '딱 하나만' 존재해야 합니다!
@bot.tree.command(name="주식설명", description="시장에 상장된 기업들의 상세 도감을 확인합니다.")
async def stock_description_command(interaction: discord.Interaction):
    global STOCKS_FILE
    
    # 💡 여기서도 안전하게 utf-8로 로드합니다.
    try:
        with open(STOCKS_FILE, "r", encoding="utf-8") as f:
            stock_data_current = json.load(f)
    except Exception:
        stock_data_current = {}

    if not stock_data_current:
        await interaction.response.send_message("📊 현재 시장에 상장된 기업이 없습니다.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 가상 기업 도감", 
        description="아래 드롭다운 메뉴를 열어 상세 설명을 확인할 기업을 골라주세요.", 
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(
        embed=embed, 
        view=StockDescriptionView(stock_data_current), 
        ephemeral=True
    )

# 🏆 /랭킹 UI 핸들러 클래스들
class RankingSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="🥇 순자산 랭킹 (빚 포함)", description="현금 + 주식가치 - 빚 (진짜 내 재산 순위)", value="net_worth"),
            discord.SelectOption(label="🥈 실자산 랭킹 (빚 제외)", description="현금 + 주식가치 (외형 재산 순위)", value="gross_asset")
        ]
        super().__init__(placeholder="조회할 랭킹 종류를 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        ranking_type = self.values[0]
        user_wallets = load_data(USERS_FILE, {})
        stock_data = load_data(STOCKS_FILE, {})
        
        leaderboard = []

        for u_id, info in user_wallets.items():
            member = interaction.guild.get_member(int(u_id))
            if not member: continue

            cash = info.get("money", 0)
            debt = info.get("debt", 0)
            my_stocks = info.get("stocks", {})

            total_stock_value = 0
            for s_name, owned_amount in my_stocks.items():
                if owned_amount > 0:
                    current_unit_price = stock_data.get(s_name, {}).get("price", 0)
                    total_stock_value += (current_unit_price * owned_amount)

            if ranking_type == "net_worth":
                score = cash + total_stock_value - debt
            else:
                score = cash + total_stock_value

            leaderboard.append((member.display_name, score))

        leaderboard.sort(key=lambda x: x[1], reverse=True)

        title_text = "🥇 서버 순자산 랭킹 (빚 포함)" if ranking_type == "net_worth" else "🥈 서버 실자산 랭킹 (빚 제외)"
        color_theme = discord.Color.gold() if ranking_type == "net_worth" else discord.Color.light_gray()
        embed = discord.Embed(
            title=title_text,
            description="💰 금액은 비공개 처리되며, 순위와 닉네임만 표시됩니다.\n━━━━━━━━━━━━━━━━━━━━",
            color=color_theme
        )

        medals = ["👑 1위", "✨ 2위", "⭐ 3위", "🔹 4위", "🔹 5위"]
        for index, (name, score) in enumerate(leaderboard[:5]):
            embed.add_field(name=medals[index], value=f"**{name}**", inline=False)

        if not leaderboard:
            embed.description += "\n❌ 현재 순위에 표시할 활동 유저가 없습니다."

        await interaction.response.edit_message(embed=embed, view=self.view)

class RankingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RankingSelect())

@bot.tree.command(name="출석", description="하루에 한 번 출석하여 무작위 주식 투자 지원금을 받습니다.")
async def daily_attendance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    global user_wallets
    user_wallets = load_data(USERS_FILE, {})
    
    if user_id not in user_wallets:
        return await interaction.response.send_message("❌ `/주식시작`을 먼저 진행해 주세요.", ephemeral=True)
        
    # 한국 시간 기준 오늘 날짜 구하기
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    
    last_date = user_wallets[user_id].get("last_attendance", "")
    if last_date == today_str:
        return await interaction.response.send_message("❌ 오늘은 이미 출석체크를 완료하셨습니다! 내일 다시 참여해 주세요.", ephemeral=True)
        
    # 30,000원 ~ 60,000원 사이 무작위 보상 지급
    reward = random.randint(30000, 60000)
    user_wallets[user_id]["money"] += reward
    user_wallets[user_id]["last_attendance"] = today_str
    save_data(USERS_FILE, user_wallets)
    
    embed = discord.Embed(title="📆 일일 출석체크 완료!", color=discord.Color.green())
    embed.description = f"오늘의 주식 보조금이 지갑으로 입금되었습니다."
    embed.add_field(name="💵 지급 금액", value=f"`+{reward:,} 원`", inline=True)
    embed.add_field(name="💰 현재 잔고", value=f"`{user_wallets[user_id]['money']:,} 원`", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="랭킹", description="서버 주식 부자들의 명예의 전당을 확인합니다. (나에게만 보임)")
async def ranking_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 가상 주식 부자 명예의 전당",
        description="아래 드롭다운 메뉴를 선택하여 **순자산** 또는 **실자산** 랭킹을 확인해 보세요!",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=RankingView(), ephemeral=True)


# 봇 실행
bot.run(DISCORD_TOKEN)
