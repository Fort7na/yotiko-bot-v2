import os

import asyncio
import json
import csv
import io
import discord
from discord import app_commands
import sqlite3
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks

from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")


SERVER_ID = 1540772708147798197
SERVER = discord.Object(id=SERVER_ID)
LOG_CHANNEL_ID = 1568074154953936916

# Кто может верифицировать
VERIFY_ROLES = {
    1540772708382548101,  # Owner
    1542957675162112030,  # Co-Owner
    1567632023865262101,  # Administrator
    1566817636728180807,  # Curator
    1566817738545041490,  # Assistant Curator
    1553836104744968332,  # Head Moderator
    1553836137468923994,  # Senior Moderator
    1540772708147798200,  # Moderator
    1546196763088519258,  # Support
}

# Кто может выдавать роль BAN
BAN_ROLES = {
    1540772708382548101,  # Owner
    1542957675162112030,  # Co-Owner
    1567632023865262101,  # Administrator
    1566817636728180807,  # Curator
    1566817738545041490,  # Assistant Curator
    1553836104744968332,  # Head Moderator
    1553836137468923994,  # Senior Moderator
    1540772708147798200,  # Moderator
}

UNVERIFIED_ROLE_ID = 1542839936116326432
RONIN_ROLE_ID = 1540772708382548104
BAN_ROLE_ID = 1549159032902918144
WARNING_ROLE_ID = 1568086592160014447

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
db = sqlite3.connect(os.path.join(DATA_DIR, "yotiko.sqlite3"))
print("Бот использует базу:", db.execute("PRAGMA database_list").fetchone()[2])
db.execute("""
CREATE TABLE IF NOT EXISTS active_warnings (
    member_id INTEGER PRIMARY KEY,
    expires_at TEXT NOT NULL
)
""")
db.commit()
db.execute("""
CREATE TABLE IF NOT EXISTS personal_invites (
    code TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS invite_attributions (
    member_id INTEGER PRIMARY KEY,
    inviter_id INTEGER NOT NULL,
    invite_code TEXT NOT NULL
)
""")

db.commit()
columns = {
    row[1]
    for row in db.execute("PRAGMA table_info(invite_attributions)")
}

if "joined_at" not in columns:
    db.execute("ALTER TABLE invite_attributions ADD COLUMN joined_at TEXT")

db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS verification_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")
db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    member_id INTEGER PRIMARY KEY,
    banned_at TEXT NOT NULL,
    reason TEXT
)
""")

db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS point_balances (
    member_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0)
)
""")
db.commit()
db.execute("""
CREATE TABLE IF NOT EXISTS shop_role_expirations (
    member_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    preexisting INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (member_id, role_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS shop_vip_access (
    member_id INTEGER PRIMARY KEY,
    expires_at TEXT NOT NULL,
    had_overwrite INTEGER NOT NULL,
    previous_overwrite TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS nitro_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
)
""")

db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS voice_point_progress (
    member_id INTEGER PRIMARY KEY,
    activity_seconds REAL NOT NULL DEFAULT 0,
    session_seconds REAL NOT NULL DEFAULT 0,
    last_tick_at TEXT,
    last_daily_reward_at TEXT
)
""")
db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS daily_chat_rewards (
    member_id INTEGER PRIMARY KEY,
    last_reward_at TEXT NOT NULL
)
""")
db.commit()

db.execute("""
CREATE TABLE IF NOT EXISTS verification_point_rewards (
    member_id INTEGER PRIMARY KEY,
    rewarded_at TEXT NOT NULL
)
""")
db.commit()

invite_cache = {}



invite_cache = {}


def has_allowed_role(member: discord.Member, role_ids: set[int]) -> bool:
    return any(role.id in role_ids for role in member.roles)


async def log_action(guild: discord.Guild, text: str) -> None:
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel is not None:
        await channel.send(text)


@bot.event
async def on_ready():
    await bot.tree.sync(guild=SERVER)
    print(f"Бот запущен: {bot.user}")

    if not getattr(bot, "_ticket_views_added", False):
        bot.add_view(ПанельОбращений())
        bot.add_view(МенюОбращений())
        bot.add_view(КнопкиРешенияОбращения())
        bot._ticket_views_added = True

    if not expire_warnings.is_running():
        expire_warnings.start()

    if not expire_shop_access.is_running():
        expire_shop_access.start()

    if not getattr(bot, "_voice_points_started", False):
        db.execute(
            "UPDATE voice_point_progress "
            "SET session_seconds = 0, last_tick_at = NULL"
        )
        db.commit()

        начислять_голосовые_баллы.start()
        bot._voice_points_started = True

    for guild in bot.guilds:

        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {
                invite.code: invite.uses or 0
                for invite in invites
            }
        except discord.Forbidden:
            print(f"Нет доступа к приглашениям сервера {guild.id}")
    guild = bot.get_guild(SERVER_ID)

    if guild is not None:
        ban_role = guild.get_role(BAN_ROLE_ID)

        if ban_role is not None:
            for member in ban_role.members:
                db.execute(
                    "INSERT OR IGNORE INTO banned_users "
                    "(member_id, banned_at, reason) VALUES (?, ?, ?)",
                    (
                        member.id,
                        datetime.now(timezone.utc).isoformat(),
                        "Синхронизация при запуске",
                    ),
                )
            db.commit()


    

@bot.tree.command(
    name="вереф",
    description="Завершить верификацию участника",
    guild=SERVER,
)
@app_commands.describe(участник="Участник, прошедший проверку")
async def вереф(
    interaction: discord.Interaction,
    участник: discord.Member,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, VERIFY_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    unverified = interaction.guild.get_role(UNVERIFIED_ROLE_ID)
    ronin = interaction.guild.get_role(RONIN_ROLE_ID)

    if unverified is None or ronin is None:
        return await interaction.response.send_message(
            "Не найдена роль Ronin или «Неверифицированный».",
            ephemeral=True,
        )

    был_неверифицирован = unverified in участник.roles

    await interaction.response.defer(ephemeral=True)

    try:
        if unverified in участник.roles:
            await участник.remove_roles(unverified, reason="Верификация")

        if ronin not in участник.roles:
            await участник.add_roles(ronin, reason="Верификация")

    except discord.Forbidden:
        return await interaction.followup.send(
            "Боту не хватает прав или его роль стоит слишком низко.",
            ephemeral=True,
        )


    баллы_начислены = False

    if был_неверифицирован:
        cursor = db.execute(
            "INSERT OR IGNORE INTO verification_point_rewards "
            "(member_id, rewarded_at) VALUES (?, ?)",
            (участник.id, datetime.now(timezone.utc).isoformat()),
        )

        if cursor.rowcount == 1:
            db.execute(
                "INSERT OR IGNORE INTO point_balances (member_id, balance) "
                "VALUES (?, 0)",
                (участник.id,),
            )
            db.execute(
                "UPDATE point_balances SET balance = balance + 20 "
                "WHERE member_id = ?",
                (участник.id,),
            )
            баллы_начислены = True

        db.commit()

    db.execute(
        "INSERT INTO verification_actions "
        "(staff_id, member_id, outcome, created_at) VALUES (?, ?, ?, ?)",
        (
            interaction.user.id,
            участник.id,
            "успешно",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()

    текст_ответа = f"{участник.mention} верифицирован(а): роль Ronin выдана."
    if баллы_начислены:
        текст_ответа += " Начислено **20 баллов**."

    await interaction.followup.send(
        текст_ответа,
        ephemeral=True,
    )



    канал_верификаций = interaction.guild.get_channel(1568583778983739516)
    if канал_верификаций is not None:
        try:
            await канал_верификаций.send(
                f"✅ **Успешная верификация**\n"
                f"Участник: {участник.mention}\n"
                f"Проверку провёл(а): {interaction.user.mention}"
            )
        except discord.HTTPException as error:
            print(f"Не удалось отправить запись о верификации: {error}")

    await log_action(
        interaction.guild,
        f"**Верификация**\n"
        f"Кто проверил: {interaction.user.mention}\n"
        f"Кого проверили: {участник.mention}",
    )

@bot.tree.command(
    name="бан",
    description="Выдать участнику роль BAN",
    guild=SERVER,
)
@app_commands.describe(
    участник="Кому выдать роль BAN",
    причина="Обязательная причина",
)
async def бан(
    interaction: discord.Interaction,
    участник: discord.Member,
    причина: str,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, BAN_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if участник.id == interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Нельзя выдать роль BAN владельцу сервера.",
            ephemeral=True,
        )

    if (
        interaction.user.id != interaction.guild.owner_id
        and interaction.user.top_role <= участник.top_role
    ):
        return await interaction.response.send_message(
            "Нельзя применить BAN к участнику с такой же или более высокой ролью.",
            ephemeral=True,
        )

    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    ronin = interaction.guild.get_role(RONIN_ROLE_ID)

    if ban_role is None or ronin is None:
        return await interaction.response.send_message(
            "Не найдена роль BAN или Ronin. Проверь ID ролей.",
            ephemeral=True,
        )

    try:
        роли_для_снятия = []

        for role_id in (
            1540772708382548104,  # Ronin
            1540772708382548102,
            1540772708382548103,
        ):
            роль = interaction.guild.get_role(role_id)
            if роль is not None and роль in участник.roles:
                роли_для_снятия.append(роль)

        if роли_для_снятия:
            await участник.remove_roles(
                *роли_для_снятия,
                reason=причина,
            )

        if ban_role not in участник.roles:
            await участник.add_roles(ban_role, reason=причина)

        if участник.voice is not None:
            try:
                await участник.move_to(
                    None,
                    reason=f"Выдан BAN: {причина}",
                )
            except discord.Forbidden:
                print("BAN выдан, но боту не хватило права отключить участника от голосового канала.")
            except discord.HTTPException as error:
                print(f"BAN выдан, но не удалось отключить участника от голосового канала: {error}")


    except discord.Forbidden:
        return await interaction.response.send_message(
            "Боту не хватает прав или его роль стоит слишком низко.",
            ephemeral=True,
        )
	
    db.execute(
        "INSERT OR REPLACE INTO banned_users "
        "(member_id, banned_at, reason) VALUES (?, ?, ?)",
        (
            участник.id,
            datetime.now(timezone.utc).isoformat(),
            причина,
        ),
    )
    db.commit()



    await interaction.response.send_message(
        f"Участнику {участник.mention} выдана роль BAN.",
        ephemeral=True,
    )
    канал_банов = interaction.guild.get_channel(1568583730493263882)

    if канал_банов is not None:
        try:
            await канал_банов.send(
                f"🔨 **Выдана роль BAN**\n"
                f"Участник: {участник.mention}\n"
                f"Кто выдал: {interaction.user.mention}\n"
                f"Причина: {причина}"
            )
        except discord.HTTPException as error:
            print(f"Не удалось отправить запись о BAN: {error}")


    await log_action(
        interaction.guild,
        f"**Выдана роль BAN**\n"
        f"Участник: {участник.mention}\n"
        f"Кто выдал: {interaction.user.mention}\n"
        f"Причина: {причина}",
    )

@bot.tree.command(
    name="разбан",
    description="Снять роль BAN и вернуть участнику Ronin",
    guild=SERVER,
)
@app_commands.describe(участник="Кого разбанить")
async def разбан(
    interaction: discord.Interaction,
    участник: discord.Member,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, BAN_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if (
        interaction.user.id != interaction.guild.owner_id
        and interaction.user.top_role <= участник.top_role
    ):
        return await interaction.response.send_message(
            "Нельзя применить команду к участнику с такой же или более высокой ролью.",
            ephemeral=True,
        )

    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    ronin_role = interaction.guild.get_role(RONIN_ROLE_ID)
    был_в_бане = interaction.guild.get_role(1560751538677227662)

    if ban_role is None or ronin_role is None or был_в_бане is None:
        return await interaction.response.send_message(
            "Не найдена одна из нужных ролей. Проверь ID ролей.",
            ephemeral=True,
        )

    if ban_role not in участник.roles:
        return await interaction.response.send_message(
            "У этого участника нет роли BAN.",
            ephemeral=True,
        )

    try:
        await участник.remove_roles(ban_role, reason="Разбан через команду бота")

        if ronin_role not in участник.roles:
            await участник.add_roles(ronin_role, reason="Разбан через команду бота")

        if был_в_бане not in участник.roles:
            await участник.add_roles(был_в_бане, reason="Разбан через команду бота")

    except discord.Forbidden:
        return await interaction.response.send_message(
            "Боту не хватает прав или его роль стоит ниже управляемых ролей.",
            ephemeral=True,
        )

    db.execute(
        "DELETE FROM banned_users WHERE member_id = ?",
        (участник.id,),
    )
    db.commit()

    await interaction.response.send_message(
        f"{участник.mention} разбанен(а): роль BAN снята, Ronin возвращена.",
        ephemeral=True,
    )


    await log_action(
        interaction.guild,
        f"**Разбан**\nУчастник: {участник.mention}\n"
        f"Кто разбанил: {interaction.user.mention}",
    )

@tasks.loop(minutes=1)
async def expire_warnings():
    guild = bot.get_guild(SERVER_ID)
    if guild is None:
        return

    warning_role = guild.get_role(WARNING_ROLE_ID)
    now = datetime.now(timezone.utc)

    rows = db.execute(
        "SELECT member_id, expires_at FROM active_warnings"
    ).fetchall()

    for member_id, expires_at in rows:
        if datetime.fromisoformat(expires_at) > now:
            continue

        try:
            member = await guild.fetch_member(member_id)
        except discord.NotFound:
            db.execute(
                "DELETE FROM active_warnings WHERE member_id = ?",
                (member_id,),
            )
            db.commit()
            continue
        except discord.HTTPException:
            continue

        try:
            if warning_role and warning_role in member.roles:
                await member.remove_roles(
                    warning_role,
                    reason="Срок предупреждения — 7 дней — истёк",
                )
        except discord.Forbidden:
            continue

        db.execute(
            "DELETE FROM active_warnings WHERE member_id = ?",
            (member_id,),
        )
        db.commit()

        await log_action(
            guild,
            f"**Истёк срок предупреждения**\n"
            f"С участника {member.mention} автоматически снята роль "
            f"«Предупреждения».",
        )


@bot.tree.command(
    name="предупредить",
    description="Выдать предупреждение на 7 дней",
    guild=SERVER,
)
@app_commands.describe(
    участник="Кого предупредить",
    причина="Обязательная причина предупреждения",
)
async def предупредить(
    interaction: discord.Interaction,
    участник: discord.Member,
    причина: str,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, BAN_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if (
        interaction.user.id != interaction.guild.owner_id
        and interaction.user.top_role <= участник.top_role
    ):
        return await interaction.response.send_message(
            "Нельзя применить команду к участнику с такой же или более высокой ролью.",
            ephemeral=True,
        )

    warning_role = interaction.guild.get_role(WARNING_ROLE_ID)
    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    ronin_role = interaction.guild.get_role(RONIN_ROLE_ID)

    if warning_role is None or ban_role is None or ronin_role is None:
        return await interaction.response.send_message(
            "Не найдена роль «Предупреждения», BAN или Ronin. Проверь ID ролей.",
            ephemeral=True,
        )

    now = datetime.now(timezone.utc)
    row = db.execute(
        "SELECT expires_at FROM active_warnings WHERE member_id = ?",
        (участник.id,),
    ).fetchone()

    active_warning = row and datetime.fromisoformat(row[0]) > now

    await interaction.response.defer(ephemeral=True)

    try:
        if active_warning:
            if warning_role in участник.roles:
                await участник.remove_roles(
                    warning_role,
                    reason="Второе предупреждение — автоматический BAN",
                )

            if ronin_role in участник.roles:
                await участник.remove_roles(
                    ronin_role,
                    reason=f"Автоматический BAN. Причина: {причина}",
                )

            if ban_role not in участник.roles:
                await участник.add_roles(
                    ban_role,
                    reason=f"Второе предупреждение. Причина: {причина}",
                )

            db.execute(
                "DELETE FROM active_warnings WHERE member_id = ?",
                (участник.id,),
            )
            db.commit()

            await interaction.followup.send(
                f"У {участник.mention} уже было активное предупреждение. "
                "Выдана роль BAN, Ronin и «Предупреждения» сняты.",
                ephemeral=True,
            )

            await log_action(
                interaction.guild,
                f"**Второе предупреждение — автоматический BAN**\n"
                f"Участник: {участник.mention}\n"
                f"Кто выдал: {interaction.user.mention}\n"
                f"Причина: {причина}",
            )
            return

        expires = now + timedelta(days=7)

        if warning_role not in участник.roles:
            await участник.add_roles(
                warning_role,
                reason=причина,
            )

        db.execute(
            "INSERT OR REPLACE INTO active_warnings(member_id, expires_at) "
            "VALUES (?, ?)",
            (участник.id, expires.isoformat()),
        )
        db.commit()

        await interaction.followup.send(
            f"{участник.mention} получил(а) предупреждение на 7 дней.",
            ephemeral=True,
        )

        await log_action(
            interaction.guild,
            f"**Предупреждение**\n"
            f"Участник: {участник.mention}\n"
            f"Кто выдал: {interaction.user.mention}\n"
            f"Причина: {причина}\n"
            f"Срок истечения: <t:{int(expires.timestamp())}:F>",
        )

    except discord.Forbidden:
        await interaction.followup.send(
            "Боту не хватает прав или его роль стоит слишком низко.",
            ephemeral=True,
        )

@bot.tree.command(
    name="таймаут",
    description="Выдать участнику тайм-аут",
    guild=SERVER,
)
@app_commands.describe(
    участник="Кого ограничить",
    минуты="Длительность от 1 до 40320 минут",
    причина="Обязательная причина",
)
async def таймаут(
    interaction: discord.Interaction,
    участник: discord.Member,
    минуты: app_commands.Range[int, 1, 40320],
    причина: str,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, BAN_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if (
        участник.id == interaction.guild.owner_id
        or (
            interaction.user.id != interaction.guild.owner_id
            and interaction.user.top_role <= участник.top_role
        )
    ):
        return await interaction.response.send_message(
            "Нельзя выдать тайм-аут владельцу или участнику "
            "с такой же либо более высокой ролью.",
            ephemeral=True,
        )

    до = datetime.now(timezone.utc) + timedelta(minutes=минуты)

    try:
        await участник.timeout(до, reason=причина)
        канал_мутов = interaction.guild.get_channel(1568583768065704027)

        if канал_мутов is not None:
            try:
                await канал_мутов.send(
                    f"🔇 **Выдан тайм-аут**\n"
                    f"Участник: {участник.mention}\n"
                    f"Кто выдал: {interaction.user.mention}\n"
                    f"Срок: {минуты} минут\n"
                    f"Причина: {причина}"
                )
            except discord.HTTPException as error:
                print(f"Тайм-аут выдан, но запись в канал мутов не отправлена: {error}")

    except discord.Forbidden:
        return await interaction.response.send_message(
            "Не получилось выдать тайм-аут. Проверь право бота "
            "«Модерировать участников» и положение его роли.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.response.send_message(
            "Discord не смог применить тайм-аут.",
            ephemeral=True,
        )

    await interaction.response.send_message(
        f"Для {участник.mention} установлен тайм-аут на {минуты} мин.",
        ephemeral=True,
    )

    await log_action(
        interaction.guild,
        f"**Тайм-аут**\n"
        f"Участник: {участник.mention}\n"
        f"Кто выдал: {interaction.user.mention}\n"
        f"Срок: {минуты} мин.\n"
        f"Причина: {причина}",
    )

@bot.tree.command(
    name="say",
    description="Отправить оформленное сообщение от имени бота",
    guild=SERVER,
)
@app_commands.describe(
    заголовок="Заголовок карточки",
    текст="Текст внутри карточки",
    картинка="Необязательная картинка",
)
async def say(
    interaction: discord.Interaction,
    заголовок: str | None = None,
    текст: str | None = None,
    картинка: discord.Attachment | None = None,
):
    SAY_ROLES = {
       1540772708382548101,  # Owner
       1542957675162112030,  # Co-Owner
       1567632023865262101,  # Administrator
       1566817636728180807,  # Curator
       1566817738545041490,  # Assistant Curator
    }


    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, SAY_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if not заголовок and not текст and not картинка:
        return await interaction.response.send_message(
            "Добавь заголовок, текст или картинку.",
            ephemeral=True,
        )

    if заголовок and len(заголовок) > 256:
        return await interaction.response.send_message(
            "Заголовок слишком длинный — максимум 256 символов.",
            ephemeral=True,
        )

    if текст and len(текст) > 4000:
        return await interaction.response.send_message(
            "Текст слишком длинный — сократи его до 4000 символов.",
            ephemeral=True,
        )

    if картинка and (
        not картинка.content_type
        or not картинка.content_type.startswith("image/")
    ):
        return await interaction.response.send_message(
            "Прикрепи файл изображения.",
            ephemeral=True,
        )

    карточка = discord.Embed(
        title=заголовок or None,
        description=текст or None,
        color=discord.Color.from_rgb(128, 0, 128),
    )

    файл = None
    if картинка:
        файл = await картинка.to_file()
        карточка.set_image(url=f"attachment://{файл.filename}")

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        await interaction.channel.send(
            embed=карточка,
            file=файл,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            "У бота нет прав отправлять сообщения или прикреплять файлы в этом канале.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            "Discord не смог отправить карточку. Попробуй ещё раз.",
            ephemeral=True,
        )

    await log_action(
        interaction.guild,
        f"**Команда /say**\n"
        f"Кто отправил: {interaction.user.mention}\n"
        f"Канал: {interaction.channel.mention}\n"
        f"Заголовок: {заголовок or 'нет'}\n"
        f"Изображение: {картинка.filename if картинка else 'нет'}",
    )

    await interaction.followup.send(
        "Карточка отправлена.",
        ephemeral=True,
    )


@bot.tree.command(
    name="разделы",
    description="Показать разделы и информацию сервера",
    guild=SERVER,
)
async def разделы(interaction: discord.Interaction):
    restricted_roles = {
        1542839936116326432,  # Неверифицированный
        1549918115582967819,  # Не прошёл верификацию
        1549159032902918144,  # BAN
    }

    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if any(role.id in restricted_roles for role in interaction.user.roles):
        return await interaction.response.send_message(
            "Команда недоступна для твоей роли.",
            ephemeral=True,
        )

    embed = discord.Embed(
        title="⛩️ Yotiko — разделы сервера",
        description="Краткая навигация по основным разделам.",
        color=discord.Color.from_rgb(128, 0, 128),
    )

    embed.add_field(
        name="📜 Правила",
        value="<#1540772709389172739>\nПравила сообщества.",
        inline=False,
    )
    embed.add_field(
        name="🌸 О сервере",
        value="<#1540772709389172736>\nДля чего создан сервер и какие интересы здесь можно найти.",
        inline=False,
    )
    embed.add_field(
        name="📰 Новости",
        value="<#1540772709389172738>\nНовости и объявления сервера.",
        inline=False,
    )
    embed.add_field(
        name="🤝 Партнёрская программа",
        value="<#1561792567908106363>\nИнформация о рекламе и партнёрстве.",
        inline=False,
    )
    embed.add_field(
        name="🎉 Ивенты",
        value="<#1545522026310275152>\nСобытия и правила игр, например «Бункер» и «Мафия».",
        inline=False,
    )
    embed.add_field(
        name="🎁 Розыгрыши",
        value="<#1544860505598992434>\nИнформация о проводимых розыгрышах.",
        inline=False,
    )
    embed.add_field(
        name="📝 Заявки",
        value="<#1553130000792821882>\nЗаявки на специальные роли, например Support или Moderator.",
        inline=False,
    )
    embed.add_field(
        name="🆘 Поддержка",
        value="<#1551038451686842408>\nОбращения и жалобы на нарушения правил.",
        inline=False,
    )
    embed.add_field(
        name="📁 Полезные файлы",
        value="<#1545831143742640168>\nПолезные материалы, например файлы для VPN и Discord.",
        inline=False,
    )
    embed.add_field(
        name="🔗 Интеграции",
        value="<#1540772709389172740>\nИнформация об интеграции Discord и Telegram.",
        inline=False,
    )


    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    try:
        invites = await member.guild.invites()
        старые_счётчики = invite_cache.get(member.guild.id)

        if старые_счётчики is not None:
            использованные = [
                invite for invite in invites
                if (invite.uses or 0) > старые_счётчики.get(invite.code, 0)
            ]

            if использованные:
                invite = использованные[0]

                if invite.inviter is not None:
                    личная_ссылка = db.execute(
                        "SELECT owner_id FROM personal_invites WHERE code = ?",
                        (invite.code,),
                    ).fetchone()

                    if личная_ссылка:
                        cursor = db.execute(
                            "INSERT OR IGNORE INTO invite_attributions "
                            "(member_id, inviter_id, invite_code, joined_at) "
                            "VALUES (?, ?, ?, ?)",
                            (
                                member.id,
                                личная_ссылка[0],
                                invite.code,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )

                        if cursor.rowcount == 1:
                            db.execute(
                                "INSERT OR IGNORE INTO point_balances "
                                "(member_id, balance) VALUES (?, 0)",
                                (личная_ссылка[0],),
                            )
                            db.execute(
                                "UPDATE point_balances "
                                "SET balance = balance + 10 "
                                "WHERE member_id = ?",
                                (личная_ссылка[0],),
                            )

                        db.commit()

        invite_cache[member.guild.id] = {
            invite.code: invite.uses or 0
            for invite in invites
        }

    except discord.Forbidden:
        print("Нет доступа к списку приглашений.")
    except discord.HTTPException as error:
        print(f"Не удалось проверить приглашения: {error}")

    бан = db.execute(
        "SELECT reason FROM banned_users WHERE member_id = ?",
        (member.id,),
    ).fetchone()

    if бан:
        ban_role = member.guild.get_role(BAN_ROLE_ID)

        if ban_role is not None:
            try:
                await member.add_roles(
                    ban_role,
                    reason="Возврат на сервер с активным BAN",
                )
            except discord.Forbidden:
                await log_action(
                    member.guild,
                    f"Не удалось вернуть роль BAN участнику {member.mention}. "
                    "Проверь права и положение роли бота.",
                )

        await log_action(
            member.guild,
            f"**Повторный вход с активным BAN**\n"
            f"Участник: {member.mention} (`{member.id}`)\n"
            f"Роль BAN выдана автоматически.",
        )
        return


    role = member.guild.get_role(1542839936116326432)

    if role is None:
        await log_action(
            member.guild,
            "Не найдена роль «Неверифицированный»."
        )
        return

    try:
        await member.add_roles(role, reason="Новый участник сервера")
        await log_action(
            member.guild,
            f"**Новый участник**\n"
            f"{member.mention} получил роль «Неверифицированный»."
        )
    except discord.Forbidden:
        await log_action(
            member.guild,
            f"Не удалось выдать роль «Неверифицированный» участнику "
            f"{member.mention}. Проверь права и положение роли бота."
        )
@bot.tree.command(
    name="очистка",
    description="Удалить сообщения за выбранный период в этом канале",
    guild=SERVER,
)
@app_commands.choices(период=[
    app_commands.Choice(name="5 минут", value=300),
    app_commands.Choice(name="15 минут", value=900),
    app_commands.Choice(name="1 час", value=3600),
    app_commands.Choice(name="6 часов", value=21600),
    app_commands.Choice(name="12 часов", value=43200),
    app_commands.Choice(name="1 день", value=86400),
])
@app_commands.describe(период="Насколько старые сообщения удалить")
async def очистка(
    interaction: discord.Interaction,
    период: app_commands.Choice[int],
):
    CLEANUP_ROLES = {
        1540772708382548101,  # Owner
        1542957675162112030,  # Co-Owner
        1567632023865262101,  # Administrator
    }

    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, CLEANUP_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    канал = interaction.channel

    if not isinstance(канал, discord.TextChannel):
        return await interaction.response.send_message(
            "Используй эту команду в обычном текстовом канале.",
            ephemeral=True,
        )

    права = канал.permissions_for(interaction.guild.me)

    if not права.view_channel or not права.read_message_history or not права.manage_messages:
        return await interaction.response.send_message(
            "В этом канале боту нужны права «Просматривать канал», "
            "«Читать историю сообщений» и «Управлять сообщениями».",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)

    начало_периода = datetime.now(timezone.utc) - timedelta(
        seconds=период.value
    )

    try:
        удалённые_сообщения = await канал.purge(
            after=начало_периода,
            limit=None,
            reason=f"/очистка — {interaction.user} — {период.name}",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            "Discord не разрешил удаление. Проверь права бота в этом канале.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            "Не удалось удалить сообщения. Попробуй ещё раз.",
            ephemeral=True,
        )

    await interaction.followup.send(
        f"Удалено сообщений: **{len(удалённые_сообщения)}**. "
        f"Период: **{период.name}**.",
        ephemeral=True,
    )

    await log_action(
        interaction.guild,
        f"**Очистка сообщений**\n"
        f"Канал: {канал.mention}\n"
        f"Кто очистил: {interaction.user.mention}\n"
        f"Период: {период.name}\n"
        f"Удалено сообщений: {len(удалённые_сообщения)}",
    )

ОГРАНИЧЕННЫЕ_РОЛИ = {
    1542839936116326432,  # Неверифицированный
    1549918115582967819,  # Не прошёл верификацию
    1549159032902918144,  # BAN
}

ТИПЫ_ОБРАЩЕНИЙ = {
    "жалоба": {
        "название": "Жалоба на пользователя",
        "эмодзи": "⚔️",
        "канал": 1568581187222638803,
    },
    "идея": {
        "название": "Идея или личная проблема",
        "эмодзи": "💡",
        "канал": 1568581233238089909,
    },
    "стафф": {
        "название": "Заявка на роль в стафф",
        "эмодзи": "🛡️",
        "канал": 1568581197544693790,
    },
    "контент": {
        "название": "Заявка на стримера или ивентера",
        "эмодзи": "🎬",
        "канал": 1568581213537443921,
    },
}


def может_подать_обращение(member: discord.Member) -> bool:
    return not any(role.id in ОГРАНИЧЕННЫЕ_РОЛИ for role in member.roles)


class ОбращениеМодал(discord.ui.Modal):
    def __init__(self, тип: str):
        данные = ТИПЫ_ОБРАЩЕНИЙ[тип]
        super().__init__(title=данные["название"][:45])
        self.тип = тип

        self.тема = discord.ui.TextInput(
            label="Тема",
            max_length=100,
            placeholder="Коротко о сути обращения",
        )
        self.описание = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            max_length=3000,
            placeholder="Опиши ситуацию подробнее",
        )
        self.файлы = discord.ui.FileUpload(
            required=False,
            min_values=0,
            max_values=5,
            custom_id="ticket_files",
        )

        self.add_item(self.тема)
        self.add_item(self.описание)
        self.add_item(
            discord.ui.Label(
                text="Фото или видео — доказательства",
                component=self.файлы,
            )
        )



    async def on_submit(self, interaction: discord.Interaction):
        данные = ТИПЫ_ОБРАЩЕНИЙ[self.тип]
        канал = interaction.guild.get_channel(данные["канал"])

        if канал is None:
            return await interaction.response.send_message(
                "Канал для этого обращения не найден. Сообщи администрации.",
                ephemeral=True,
            )

        файлы = []
        for вложение in self.файлы.values:
            файлы.append(await вложение.to_file())

        карточка = discord.Embed(
            title=f"{данные['эмодзи']} {данные['название']}",
            description=self.описание.value,
            color=discord.Color.from_rgb(128, 0, 128),
            timestamp=datetime.now(timezone.utc),
        )
        изображения = [
            вложение
            for вложение in self.файлы.values
            if вложение.content_type
            and вложение.content_type.startswith("image/")
        ]

        if изображения:
            карточка.set_image(
                url=f"attachment://{изображения[0].filename}"
            )

        карточка.add_field(
            name="Тема",
            value=self.тема.value,
            inline=False,
        )
        карточка.add_field(
            name="От кого",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        if файлы:
            карточка.add_field(
                name="Вложения",
                value=", ".join(f.filename for f in файлы),
                inline=False,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            await канал.send(
                embed=карточка,
                files=файлы or discord.utils.MISSING,
		view=КнопкиРешенияОбращения(),
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "Бот не может отправить обращение в нужный канал: "
                "проверь права на просмотр, отправку сообщений и файлов.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                "Не удалось отправить обращение с файлами. Возможно, файл слишком большой.",
                ephemeral=True,
            )

        await interaction.followup.send(
            f"Обращение отправлено в {канал.mention}.",
            ephemeral=True,
        )

        await log_action(
            interaction.guild,
            f"**Новое обращение**\n"
            f"Тип: {данные['название']}\n"
            f"Автор: {interaction.user.mention}\n"
            f"Тема: {self.тема.value}\n"
            f"Файлов: {len(файлы)}\n"
            f"Канал: {канал.mention}",
        )


class ОбращениеМеню(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=данные["название"],
                value=ключ,
                emoji=данные["эмодзи"],
            )
            for ключ, данные in ТИПЫ_ОБРАЩЕНИЙ.items()
        ]
        super().__init__(
            placeholder="Выбери, куда отправить обращение",
            options=options,
            custom_id="yotiko_ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ОбращениеМодал(self.values[0]))


class МенюОбращений(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ОбращениеМеню())


class ПанельОбращений(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Создать обращение",
        emoji="📩",
        style=discord.ButtonStyle.primary,
        custom_id="yotiko_ticket_open",
    )
    async def открыть(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Команда доступна только на сервере.",
                ephemeral=True,
            )

        if not может_подать_обращение(interaction.user):
            return await interaction.response.send_message(
                "С твоими ролями подать обращение нельзя.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "Выбери тип обращения:",
            view=МенюОбращений(),
            ephemeral=True,
        )


РЕШАЮЩИЕ_РОЛИ = {
    1540772708382548101,  # Owner
    1542957675162112030,  # Co-Owner
    1567632023865262101,  # Administrator
    1566817636728180807,  # Curator
    1566817738545041490,  # Assistant Curator
}


class КнопкиРешенияОбращения(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def решить(self, interaction: discord.Interaction, принято: bool):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Эта кнопка доступна только на сервере.",
                ephemeral=True,
            )

        if (
            interaction.user.id != interaction.guild.owner_id
            and not any(
                роль.id in РЕШАЮЩИЕ_РОЛИ
                for роль in interaction.user.roles
            )
        ):
            return await interaction.response.send_message(
                "У тебя нет доступа к этой кнопке.",
                ephemeral=True,
            )

        сообщение = interaction.message
        if not сообщение.embeds:
            return await interaction.response.send_message(
                "Не удалось прочитать обращение.",
                ephemeral=True,
            )

        карточка = сообщение.embeds[0].copy()

        if any(
            поле.name == "Решение"
            for embed in сообщение.embeds
            for поле in embed.fields
        ):
            return await interaction.response.send_message(
                "По этому обращению уже принято решение.",
                ephemeral=True,
            )

        id_автора = None
        for поле in карточка.fields:
            if поле.name.lower() in {"от кого", "автор"}:
                первая_часть = поле.value.split(maxsplit=1)[0]
                цифры = (
                    первая_часть
                    .replace("<@", "")
                    .replace("!", "")
                    .replace(">", "")
                )
                if цифры.isdigit():
                    id_автора = int(цифры)
                break

        if id_автора is None:
            return await interaction.response.send_message(
                "Не удалось определить автора обращения. Проверь поле «От кого» в карточке.",
                ephemeral=True,
            )

        решение = "принята" if принято else "отклонена"
        карточка.add_field(
            name="Решение",
            value=f"Заявка {решение}. Рассмотрел(а): {interaction.user.mention}",
            inline=False,
        )
        карточка.color = (
            discord.Color.green() if принято else discord.Color.red()
        )

        for кнопка in self.children:
            кнопка.disabled = True

        await interaction.response.edit_message(
            embed=карточка,
            view=self,
        )

        текст_для_личного_сообщения = (
            f"Ваша заявка **принята** на сервере Yotiko."
            if принято
            else f"Ваша заявка **отклонена** на сервере Yotiko."
        )

        try:
            пользователь = await interaction.client.fetch_user(id_автора)
            await пользователь.send(текст_для_личного_сообщения)
            результат_личного = "Личное сообщение отправлено."
        except (discord.Forbidden, discord.HTTPException):
            результат_личного = (
                "Не удалось отправить личное сообщение — возможно, "
                "у пользователя закрыты ЛС."
            )

        await interaction.followup.send(
            f"Решение записано. {результат_личного}",
            ephemeral=True,
        )

        await log_action(
            interaction.guild,
            f"**Решение по обращению**\n"
            f"Результат: {решение}\n"
            f"Рассмотрел(а): {interaction.user.mention}\n"
            f"Канал обращения: {сообщение.channel.mention}",
        )

    @discord.ui.button(
        label="Принять",
        style=discord.ButtonStyle.success,
        custom_id="yotiko_ticket_accept",
    )
    async def принять(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.решить(interaction, принято=True)

    @discord.ui.button(
        label="Отказать",
        style=discord.ButtonStyle.danger,
        custom_id="yotiko_ticket_reject",
    )
    async def отказать(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.решить(interaction, принято=False)

@bot.tree.command(
    name="обращения",
    description="Отправить панель создания обращений в этот канал",
    guild=SERVER,
)
async def обращения(interaction: discord.Interaction):
    ПАНЕЛЬ_РОЛИ = {
        1540772708382548101,  # Owner
        1542957675162112030,  # Co-Owner
        1567632023865262101,  # Administrator
        1566817636728180807,  # Curator
        1566817738545041490,  # Assistant Curator
        1553836104744968332,  # Head Moderator
        1553836137468923994,  # Senior Moderator
    }

    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, ПАНЕЛЬ_РОЛИ):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    карточка = discord.Embed(
        title="📩 Обращения Yotiko",
        description=(
            "Нажми кнопку ниже и выбери тип обращения.\n\n"
            "⚔️ Жалоба на пользователя\n"
            "💡 Идея или личная проблема\n"
            "🛡️ Заявка на роль в стафф\n"
            "🎬 Заявка на стримера или ивентера"
        ),
        color=discord.Color.from_rgb(128, 0, 128),
    )

    await interaction.channel.send(
        embed=карточка,
        view=ПанельОбращений(),
    )
    await interaction.response.send_message(
        "Панель обращений отправлена.",
        ephemeral=True,
    )

@bot.tree.command(
    name="невериф",
    description="Отметить, что участник не прошёл верификацию",
    guild=SERVER,
)
@app_commands.describe(участник="Кому выдать роль «Не прошёл верификацию»")
async def невериф(
    interaction: discord.Interaction,
    участник: discord.Member,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, VERIFY_ROLES):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    невериф_role = interaction.guild.get_role(1549918115582967819)
    новичок_role = interaction.guild.get_role(1542839936116326432)
    ronin_role = interaction.guild.get_role(1540772708382548104)

    if невериф_role is None or новичок_role is None or ronin_role is None:
        return await interaction.response.send_message(
            "Не найдена одна из ролей. Проверь ID ролей.",
            ephemeral=True,
        )

    try:
        if новичок_role in участник.roles:
            await участник.remove_roles(
                новичок_role,
                reason=f"Верификация не пройдена: {interaction.user}",
            )

        if ronin_role in участник.roles:
            await участник.remove_roles(
                ronin_role,
                reason=f"Верификация не пройдена: {interaction.user}",
            )

        if невериф_role not in участник.roles:
            await участник.add_roles(
                невериф_role,
                reason=f"Верификация не пройдена: {interaction.user}",
            )

    except discord.Forbidden:
        return await interaction.response.send_message(
            "Не получилось изменить роли. Проверь право «Управлять ролями» "
            "и положение роли бота.",
            ephemeral=True,
        )

    db.execute("""
        CREATE TABLE IF NOT EXISTS verification_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    db.execute(
        "INSERT INTO verification_actions "
        "(staff_id, member_id, outcome, created_at) VALUES (?, ?, ?, ?)",
        (
            interaction.user.id,
            участник.id,
            "не прошёл верификацию",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()
    канал_верификаций = interaction.guild.get_channel(1568583778983739516)

    if канал_верификаций is not None:
        try:
            await канал_верификаций.send(
                f"⚠️ **Верификация не пройдена**\n"
                f"Участник: {участник.mention}\n"
                f"Проверку провёл(а): {interaction.user.mention}"
            )
        except discord.HTTPException as error:
            print(f"Не удалось отправить запись о верификации: {error}")


    await interaction.response.send_message(
        f"{участник.mention}: роль «Не прошёл верификацию» выдана.",
        ephemeral=True,
    )

    await log_action(
        interaction.guild,
        f"**Верификация не пройдена**\n"
        f"Участник: {участник.mention}\n"
        f"Кто провёл проверку: {interaction.user.mention}",
    )

STATS_ALLOWED_ROLES = {
    1540772708382548101,   # Owner
    1542957675162112030,   # Co-Owner
    1567632023865262101,   # Administrator
    1566817636728180807,   # Curator
    1566817738545041490,   # Assistant Curator
    1553836104744968332,   # Head Moderator
    1553836137468923994,   # Senior Moderator
    1540772708147798200,   # Moderator
    1546196763088519258,   # Support
    1543029807678357595,   # Eventer
    1543029471186133052,   # Streamer
    1540772708382548104,   # Ronin
}

STATS_BLOCKED_ROLES = {
    1542839936116326432,   # Неверифицированный
    1549918115582967819,   # Не прошёл верификацию
    1549159032902918144,   # BAN
}


def can_view_own_stats(member: discord.Member) -> bool:
    if has_allowed_role(member, STATS_BLOCKED_ROLES):
        return False
    return has_allowed_role(member, STATS_ALLOWED_ROLES)


@bot.tree.command(
    name="мояссылка",
    description="Создать или показать личную ссылку-приглашение",
    guild=SERVER,
)
async def мояссылка(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not can_view_own_stats(interaction.user):
        return await interaction.response.send_message(
            "Команда доступна только верифицированным участникам.",
            ephemeral=True,
        )

    канал = interaction.channel
    if not isinstance(канал, (discord.TextChannel, discord.VoiceChannel)):
        return await interaction.response.send_message(
            "Вызови команду в текстовом или голосовом канале.",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)

    try:
        активные = await interaction.guild.invites()
    except discord.Forbidden:
        return await interaction.followup.send(
            "Боту нужно право «Управлять сервером», чтобы проверять приглашения.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            "Не удалось загрузить приглашения сервера. Попробуй позже.",
            ephemeral=True,
        )

    активные_по_коду = {invite.code: invite for invite in активные}
    сохранённые = db.execute(
        "SELECT code FROM personal_invites WHERE owner_id = ?",
        (interaction.user.id,),
    ).fetchall()

    for (code,) in сохранённые:
        if code in активные_по_коду:
            invite = активные_по_коду[code]
            invite_cache.setdefault(interaction.guild.id, {})[code] = invite.uses or 0
            return await interaction.followup.send(
                f"Твоя личная ссылка: {invite.url}",
                ephemeral=True,
            )

    try:
        invite = await канал.create_invite(
            max_age=0,
            max_uses=0,
            unique=True,
            reason=f"Личная ссылка участника {interaction.user.id}",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            "Боту нужно право «Создавать приглашения» в этом канале.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            "Не удалось создать ссылку. Попробуй позже.",
            ephemeral=True,
        )

    db.execute(
        "INSERT OR REPLACE INTO personal_invites "
        "(code, owner_id, channel_id) VALUES (?, ?, ?)",
        (invite.code, interaction.user.id, канал.id),
    )
    db.commit()

    invite_cache.setdefault(interaction.guild.id, {})[invite.code] = invite.uses or 0

    await interaction.followup.send(
        f"Твоя личная ссылка: {invite.url}",
        ephemeral=True,
    )


@bot.tree.command(
    name="статистика",
    description="Показать свою статистику приглашений и проверок",
    guild=SERVER,
)
async def статистика(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not can_view_own_stats(interaction.user):
        return await interaction.response.send_message(
            "Статистика доступна только верифицированным участникам.",
            ephemeral=True,
        )

    приглашено = db.execute(
        "SELECT COUNT(*) FROM invite_attributions WHERE inviter_id = ?",
        (interaction.user.id,),
    ).fetchone()[0]

    успешно = db.execute(
        "SELECT COUNT(*) FROM verification_actions "
        "WHERE staff_id = ? AND outcome = 'успешно'",
        (interaction.user.id,),
    ).fetchone()[0]

    карточка = discord.Embed(
        title=f"Статистика — {interaction.user.display_name}",
        color=discord.Color.from_rgb(128, 0, 128),
    )
    карточка.add_field(
        name="Пришло по твоей ссылке",
        value=str(приглашено),
    )
    карточка.add_field(
        name="Успешно верифицировано",
        value=str(успешно),
    )
    карточка.set_footer(
        text="Учёт начинается с момента запуска этой функции."
    )

    await interaction.response.send_message(embed=карточка, ephemeral=True)


ADMIN_STATS_ROLES = {
    1540772708382548101,  # Owner
    1542957675162112030,  # Co-Owner
    1567632023865262101,  # Administrator
}

STAFF_STATS_ROLES = {
    1546196763088519258,  # Support
    1540772708147798200,  # Moderator
    1553836137468923994,  # Senior Moderator
    1553836104744968332,  # Head Moderator
    1566817738545041490,  # Assistant Curator
    1566817636728180807,  # Curator
    1567632023865262101,  # Administrator
    1542957675162112030,  # Co-Owner
    1540772708382548101,  # Owner
}


@bot.tree.command(
    name="общаястатистика",
    description="Статистика команды за выбранный период",
    guild=SERVER,
)
@app_commands.choices(период=[
    app_commands.Choice(name="24 часа (1 день)", value="1"),
    app_commands.Choice(name="7 дней", value="7"),
    app_commands.Choice(name="30 дней", value="30"),
    app_commands.Choice(name="90 дней", value="90"),
    app_commands.Choice(name="Всё время", value="all"),
])
@app_commands.describe(период="За какой период показать результаты")
async def общаястатистика(
    interaction: discord.Interaction,
    период: app_commands.Choice[str],
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, ADMIN_STATS_ROLES):
        return await interaction.response.send_message(
            "Общая статистика доступна только администрации.",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)

    if период.value == "all":
        дата_начала = None
        подпись_периода = "Всё время"
    else:
        дата_начала = (
            datetime.now(timezone.utc)
            - timedelta(days=int(период.value))
        ).isoformat()
        подпись_периода = период.name

    строки = []

    try:
        async for участник in interaction.guild.fetch_members(limit=None):
            if not any(
                роль.id in STAFF_STATS_ROLES
                for роль in участник.roles
            ):
                continue

            if дата_начала is None:
                приглашено = db.execute(
                    "SELECT COUNT(*) FROM invite_attributions "
                    "WHERE inviter_id = ?",
                    (участник.id,),
                ).fetchone()[0]

                успешно = db.execute(
                    "SELECT COUNT(*) FROM verification_actions "
                    "WHERE staff_id = ? AND outcome = 'успешно'",
                    (участник.id,),
                ).fetchone()[0]
            else:
                приглашено = db.execute(
                    "SELECT COUNT(*) FROM invite_attributions "
                    "WHERE inviter_id = ? AND joined_at >= ?",
                    (участник.id, дата_начала),
                ).fetchone()[0]

                успешно = db.execute(
                    "SELECT COUNT(*) FROM verification_actions "
                    "WHERE staff_id = ? AND outcome = 'успешно' "
                    "AND created_at >= ?",
                    (участник.id, дата_начала),
                ).fetchone()[0]

            строки.append([
                участник.display_name,
                участник.id,
                приглашено,
                успешно,
            ])

    except discord.Forbidden:
        return await interaction.followup.send(
            "Бот не смог получить список участников. Проверь настройку "
            "Server Members Intent в Developer Portal.",
            ephemeral=True,
        )

    строки.sort(key=lambda строка: строка[0].casefold())

    if not строки:
        return await interaction.followup.send(
            f"За период **{подпись_периода}** сотрудников с нужными ролями не найдено.",
            ephemeral=True,
        )

    всего_приглашено = sum(строка[2] for строка in строки)
    всего_успешно = sum(строка[3] for строка in строки)

    страницы = [
        строки[начало:начало + 20]
        for начало in range(0, len(строки), 20)
    ]

    for номер, страница in enumerate(страницы, start=1):
        карточка = discord.Embed(
            title="⛩️ Общая статистика Yotiko",
            description=f"Период: **{подпись_периода}**",
            color=discord.Color.from_rgb(128, 0, 128),
        )

        for имя, _id, приглашено, успешно in страница:
            карточка.add_field(
                name=f"👤 {имя}",
                value=(
                    f"🔗 Приглашено: **{приглашено}**  ·  "
                    f"✅ Верифицировано: **{успешно}**"
                ),
                inline=False,
            )

        карточка.add_field(
            name="📊 Всего за выбранный период",
            value=(
                f"🔗 Приглашено: **{всего_приглашено}**  ·  "
                f"✅ Верифицировано: **{всего_успешно}**"
            ),
            inline=False,
        )

        if len(страницы) > 1:
            карточка.set_footer(
                text=f"Страница {номер} из {len(страницы)}"
            )

        await interaction.followup.send(embed=карточка, ephemeral=True)


POINTS_ADMIN_ROLE_ID = 1540772708382548101


def get_points(member_id: int) -> int:
    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (member_id,),
    )
    row = db.execute(
        "SELECT balance FROM point_balances WHERE member_id = ?",
        (member_id,),
    ).fetchone()
    db.commit()
    return row[0]


@bot.tree.command(
    name="баланс",
    description="Показать свой баланс баллов",
    guild=SERVER,
)
async def баланс(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    количество = get_points(interaction.user.id)
    await interaction.response.send_message(
        f"У тебя **{количество:,} баллов**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="выдатьбаллы",
    description="Выдать участнику баллы",
    guild=SERVER,
)
@app_commands.describe(
    участник="Кому выдать баллы",
    количество="Сколько баллов выдать",
)
async def выдатьбаллы(
    interaction: discord.Interaction,
    участник: discord.Member,
    количество: int,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, {POINTS_ADMIN_ROLE_ID}):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if количество <= 0:
        return await interaction.response.send_message(
            "Количество баллов должно быть больше нуля.",
            ephemeral=True,
        )

    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (участник.id,),
    )
    db.execute(
        "UPDATE point_balances SET balance = balance + ? WHERE member_id = ?",
        (количество, участник.id),
    )
    db.commit()

    новый_баланс = get_points(участник.id)
    await interaction.response.send_message(
        f"Участнику {участник.mention} выдано **{количество:,} баллов**. "
        f"Баланс: **{новый_баланс:,}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="забратьбаллы",
    description="Забрать у участника баллы",
    guild=SERVER,
)
@app_commands.describe(
    участник="У кого забрать баллы",
    количество="Сколько баллов забрать",
)
async def забратьбаллы(
    interaction: discord.Interaction,
    участник: discord.Member,
    количество: int,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    if not has_allowed_role(interaction.user, {POINTS_ADMIN_ROLE_ID}):
        return await interaction.response.send_message(
            "У тебя нет доступа к этой команде.",
            ephemeral=True,
        )

    if количество <= 0:
        return await interaction.response.send_message(
            "Количество баллов должно быть больше нуля.",
            ephemeral=True,
        )

    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (участник.id,),
    )
    cursor = db.execute(
        "UPDATE point_balances "
        "SET balance = balance - ? "
        "WHERE member_id = ? AND balance >= ?",
        (количество, участник.id, количество),
    )
    db.commit()

    if cursor.rowcount == 0:
        return await interaction.response.send_message(
            "У участника недостаточно баллов.",
            ephemeral=True,
        )

    новый_баланс = get_points(участник.id)
    await interaction.response.send_message(
        f"У {участник.mention} забрано **{количество:,} баллов**. "
        f"Баланс: **{новый_баланс:,}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="передатьбаллы",
    description="Передать баллы другому участнику",
    guild=SERVER,
)
@app_commands.describe(
    участник="Кому передать баллы",
    количество="Сколько баллов передать",
)
async def передатьбаллы(
    interaction: discord.Interaction,
    участник: discord.Member,
    количество: int,
):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    отправитель = interaction.user

    if участник.id == отправитель.id:
        return await interaction.response.send_message(
            "Нельзя передать баллы самому себе.",
            ephemeral=True,
        )

    if количество <= 0:
        return await interaction.response.send_message(
            "Количество баллов должно быть больше нуля.",
            ephemeral=True,
        )

    if BAN_ROLE_ID in {role.id for role in отправитель.roles}:
        return await interaction.response.send_message(
            "Участники с ролью BAN не могут передавать баллы.",
            ephemeral=True,
        )

    тайм_аут_до = отправитель.communication_disabled_until
    if тайм_аут_до is not None and тайм_аут_до > datetime.now(timezone.utc):
        return await interaction.response.send_message(
            "Нельзя передавать баллы во время тайм-аута.",
            ephemeral=True,
        )

    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (отправитель.id,),
    )
    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (участник.id,),
    )

    cursor = db.execute(
        "UPDATE point_balances "
        "SET balance = balance - ? "
        "WHERE member_id = ? AND balance >= ?",
        (количество, отправитель.id, количество),
    )

    if cursor.rowcount == 0:
        db.rollback()
        return await interaction.response.send_message(
            "У тебя недостаточно баллов.",
            ephemeral=True,
        )

    db.execute(
        "UPDATE point_balances SET balance = balance + ? WHERE member_id = ?",
        (количество, участник.id),
    )
    db.commit()

    баланс_отправителя = get_points(отправитель.id)
    await interaction.response.send_message(
        f"Ты передал(а) {участник.mention} **{количество:,} баллов**. "
        f"Твой баланс: **{баланс_отправителя:,}**.",
        ephemeral=True,
    )

ТОВАРЫ_МАГАЗИНА = {
    "ultimate": {
        "название": "Ultimate",
        "описание": "Роль Ultimate на выбранное количество месяцев.",
        "роль": 1572265083323809792,
        "цена": 10000,
        "тип": "роль",
    },
    "king": {
        "название": "King",
        "описание": "Роль King на выбранное количество месяцев.",
        "роль": 1572266098890514462,
        "цена": 5000,
        "тип": "роль",
    },
    "platinum": {
        "название": "Platinum",
        "описание": "Роль Platinum на выбранное количество месяцев.",
        "роль": 1572266490366001245,
        "цена": 2500,
        "тип": "роль",
    },
    "vip": {
        "название": "Пропуск в VIP-комнату",
        "описание": "Доступ в VIP-комнату на выбранный срок.",
        "цена": 2000,
        "тип": "vip",
    },
    "nitro": {
        "название": "Discord Nitro",
        "описание": "После покупки запрос отправится администрации. "
                    "Ожидаемый срок выдачи — до 12 часов.",
        "цена": 15000,
        "тип": "nitro",
    },
}


def создать_карточку_товара(ключ: str, срок: int = 1) -> discord.Embed:
    товар = ТОВАРЫ_МАГАЗИНА[ключ]
    тип = товар["тип"]

    if тип == "роль":
        цена = товар["цена"] * срок
        срок_текст = f"{срок} мес."
        единица = f"{товар['цена']:,} баллов за месяц"
    elif тип == "vip":
        цена = товар["цена"] * срок
        срок_текст = f"{срок * 14} дней"
        единица = "2 000 баллов за каждые 14 дней"
    else:
        цена = товар["цена"]
        срок_текст = "одна покупка"
        единица = "фиксированная цена"

    карточка = discord.Embed(
        title=f"🛍️ {товар['название']}",
        description=товар["описание"],
        color=discord.Color.from_rgb(128, 0, 128),
    )
    карточка.add_field(name="Стоимость", value=единица, inline=True)
    карточка.add_field(name="Срок", value=срок_текст, inline=True)
    карточка.add_field(name="Итого", value=f"**{цена:,} баллов**", inline=True)
    карточка.set_footer(text="Выбери срок и проверь сумму перед покупкой.")
    return карточка


class ВыборТовара(discord.ui.Select):
    def __init__(self, владелец_id: int):
        self.владелец_id = владелец_id

        варианты = [
            discord.SelectOption(
                label=товар["название"],
                value=ключ,
                description=товар["описание"][:100],
            )
            for ключ, товар in ТОВАРЫ_МАГАЗИНА.items()
        ]

        super().__init__(
            placeholder="Выбери товар из каталога",
            options=варианты,
            custom_id="points_shop_product_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=создать_карточку_товара(self.values[0]),
            view=ПросмотрТовара(self.владелец_id, self.values[0]),
        )


class КаталогБаллов(discord.ui.View):
    def __init__(self, владелец_id: int):
        super().__init__(timeout=180)
        self.add_item(ВыборТовара(владелец_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.children[0].владелец_id:
            await interaction.response.send_message(
                "Это меню открыто не тобой. Вызови `/каталог`, чтобы открыть своё.",
                ephemeral=True,
            )
            return False
        return True


class ВыборСрока(discord.ui.Select):
    def __init__(self, родитель: "ПросмотрТовара"):
        self.родитель = родитель
        товар = ТОВАРЫ_МАГАЗИНА[родитель.ключ]

        if товар["тип"] == "роль":
            варианты = [
                discord.SelectOption(
                    label=f"{месяц} мес. — {товар['цена'] * месяц:,} баллов",
                    value=str(месяц),
                )
                for месяц in range(1, 13)
            ]
            placeholder = "Выбери срок роли"
        elif товар["тип"] == "vip":
            варианты = [
                discord.SelectOption(
                    label=f"{блок * 14} дней — {товар['цена'] * блок:,} баллов",
                    value=str(блок),
                )
                for блок in range(1, 13)
            ]
            placeholder = "Выбери срок VIP-доступа"
        else:
            варианты = [
                discord.SelectOption(label="Без срока", value="1")
            ]
            placeholder = "Срок для этого товара не выбирается"

        super().__init__(
            placeholder=placeholder,
            options=варианты,
            custom_id="points_shop_duration_select",
        )

    async def callback(self, interaction: discord.Interaction):
        self.родитель.срок = int(self.values[0])
        await interaction.response.edit_message(
            embed=создать_карточку_товара(
                self.родитель.ключ,
                self.родитель.срок,
            ),
            view=self.родитель,
        )


class ПросмотрТовара(discord.ui.View):
    def __init__(self, владелец_id: int, ключ: str):
        super().__init__(timeout=180)
        self.владелец_id = владелец_id
        self.ключ = ключ
        self.срок = 1
        self.add_item(ВыборСрока(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.владелец_id:
            await interaction.response.send_message(
                "Это меню открыто не тобой.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Перейти к подтверждению",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def подтвердить_выбор(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        товар = ТОВАРЫ_МАГАЗИНА[self.ключ]

        if товар["тип"] == "роль":
            сумма = товар["цена"] * self.срок
            срок_текст = f"{self.срок} мес."
        elif товар["тип"] == "vip":
            сумма = товар["цена"] * self.срок
            срок_текст = f"{self.срок * 14} дней"
        else:
            сумма = товар["цена"]
            срок_текст = "одна покупка"

        карточка = discord.Embed(
            title="🧾 Проверь заказ",
            description=(
                f"**Товар:** {товар['название']}\n"
                f"**Срок:** {срок_текст}\n"
                f"**Стоимость:** {сумма:,} баллов"
            ),
            color=discord.Color.gold(),
        )
        карточка.set_footer(
            text="На этом этапе подтверждение ещё не списывает баллы."
        )

        await interaction.response.edit_message(
            embed=карточка,
            view=ПодтверждениеЗаказа(self.владелец_id, self.ключ, self.срок),
        )


SHOP_LOCK = asyncio.Lock()
NITRO_NOTIFY_USER_IDS = (
    425291008889192448,
    787987438240137237,
)
VIP_CHANNEL_ID = 1571261347528839258


def стоимость_товара(ключ: str, срок: int) -> int:
    товар = ТОВАРЫ_МАГАЗИНА[ключ]

    if товар["тип"] in {"роль", "vip"}:
        return товар["цена"] * срок

    return товар["цена"]


def списать_баллы(member_id: int, количество: int) -> bool:
    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) VALUES (?, 0)",
        (member_id,),
    )
    курсор = db.execute(
        "UPDATE point_balances SET balance = balance - ? "
        "WHERE member_id = ? AND balance >= ?",
        (количество, member_id, количество),
    )
    db.commit()
    return курсор.rowcount == 1


def вернуть_баллы(member_id: int, количество: int) -> None:
    db.execute(
        "UPDATE point_balances SET balance = balance + ? WHERE member_id = ?",
        (количество, member_id),
    )
    db.commit()


async def оформить_покупку(
    interaction: discord.Interaction,
    ключ: str,
    срок: int,
) -> str:
    товар = ТОВАРЫ_МАГАЗИНА[ключ]
    тип = товар["тип"]
    цена = стоимость_товара(ключ, срок)
    участник = interaction.user
    сейчас = datetime.now(timezone.utc)

    async with SHOP_LOCK:
        if not списать_баллы(участник.id, цена):
            return "Недостаточно баллов. Покупка не оформлена."

        if тип == "роль":
            роль = interaction.guild.get_role(товар["роль"])
            if роль is None:
                вернуть_баллы(участник.id, цена)
                return "Роль товара не найдена. Баллы возвращены; сообщи администрации."

            прежняя_запись = db.execute(
                "SELECT expires_at, preexisting FROM shop_role_expirations "
                "WHERE member_id = ? AND role_id = ?",
                (участник.id, роль.id),
            ).fetchone()

            была_роль_до_покупки = роль in участник.roles

            try:
                if not была_роль_до_покупки:
                    await участник.add_roles(роль, reason="Покупка в магазине")
            except discord.Forbidden:
                вернуть_баллы(участник.id, цена)
                return "Бот не смог выдать роль. Баллы возвращены; проверь права и порядок ролей."

            начало = сейчас
            if прежняя_запись:
                старое_окончание = datetime.fromisoformat(прежняя_запись[0])
                if старое_окончание > сейчас:
                    начало = старое_окончание
                была_роль_до_покупки = bool(прежняя_запись[1])

            окончание = начало + timedelta(days=30 * срок)

            db.execute(
                """
                INSERT INTO shop_role_expirations
                    (member_id, role_id, expires_at, preexisting)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(member_id, role_id)
                DO UPDATE SET expires_at = excluded.expires_at
                """,
                (
                    участник.id,
                    роль.id,
                    окончание.isoformat(),
                    int(была_роль_до_покупки),
                ),
            )
            db.commit()

            return (
                f"Покупка оформлена: роль **{товар['название']}** выдана "
                f"или продлена на **{срок} мес.**. "
                f"Списано **{цена:,} баллов**."
            )

        if тип == "vip":
            канал = interaction.guild.get_channel(VIP_CHANNEL_ID)
            if канал is None:
                вернуть_баллы(участник.id, цена)
                return "VIP-комната не найдена. Баллы возвращены; сообщи администрации."

            прежняя_запись = db.execute(
                "SELECT expires_at, had_overwrite, previous_overwrite "
                "FROM shop_vip_access WHERE member_id = ?",
                (участник.id,),
            ).fetchone()

            текущий_overwrite = канал.overwrites_for(участник)
            был_персональный_overwrite = участник in канал.overwrites
            текущий_json = json.dumps(текущий_overwrite.to_dict())

            начало = сейчас
            if прежняя_запись:
                старое_окончание = datetime.fromisoformat(прежняя_запись[0])
                if старое_окончание > сейчас:
                    начало = старое_окончание
                исходный_overwrite_был = bool(прежняя_запись[1])
                исходный_overwrite = прежняя_запись[2]
            else:
                исходный_overwrite_был = был_персональный_overwrite
                исходный_overwrite = текущий_json if был_персональный_overwrite else None

            новый_overwrite = канал.overwrites_for(участник)
            новый_overwrite.view_channel = True
            новый_overwrite.connect = True

            try:
                await канал.set_permissions(
                    участник,
                    overwrite=новый_overwrite,
                    reason="Покупка VIP-доступа",
                )
            except discord.Forbidden:
                вернуть_баллы(участник.id, цена)
                return "Бот не смог открыть доступ к VIP-комнате. Баллы возвращены."

            окончание = начало + timedelta(days=14 * срок)

            try:
                db.execute(
                    """
                    INSERT INTO shop_vip_access
                        (member_id, expires_at, had_overwrite, previous_overwrite)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(member_id)
                    DO UPDATE SET expires_at = excluded.expires_at
                    """,
                    (
                        участник.id,
                        окончание.isoformat(),
                        int(исходный_overwrite_был),
                        исходный_overwrite,
                    ),
                )
                db.commit()
            except sqlite3.Error:
                await канал.set_permissions(
                    участник,
                    overwrite=текущий_overwrite if был_персональный_overwrite else None,
                    reason="Откат неудачной покупки VIP-доступа",
                )
                вернуть_баллы(участник.id, цена)
                return "Не удалось сохранить покупку. Баллы возвращены."

            return (
                f"VIP-доступ открыт на **{срок * 14} дней**. "
                f"Списано **{цена:,} баллов**."
            )

        if тип == "nitro":
            db.execute(
                "INSERT INTO nitro_orders (member_id, created_at, status) "
                "VALUES (?, ?, ?)",
                (участник.id, сейчас.isoformat(), "ожидает выдачи"),
            )
            db.commit()

            отправлено = 0
            for user_id in NITRO_NOTIFY_USER_IDS:
                try:
                    получатель = await bot.fetch_user(user_id)
                    await получатель.send(
                        "💎 **Новый заказ Discord Nitro**\n"
                        f"Покупатель: {участник} (`{участник.id}`)\n"
                        f"Дата: <t:{int(сейчас.timestamp())}:F>\n"
                        f"Стоимость: **{цена:,} баллов**\n"
                        "Ожидаемый срок выдачи: до 12 часов."
                    )
                    отправлено += 1
                except (discord.Forbidden, discord.HTTPException) as ошибка:
                    print(f"Не удалось уведомить получателя Nitro {user_id}: {ошибка}")

            return (
                f"Запрос на Discord Nitro отправлен. Ожидаемое время выдачи — "
                f"до 12 часов. Списано **{цена:,} баллов**. "
                f"Уведомлено администраторов: **{отправлено}/2**."
            )

        вернуть_баллы(участник.id, цена)
        return "Неизвестный товар. Баллы возвращены."


@tasks.loop(minutes=1)
async def expire_shop_access():
    guild = bot.get_guild(SERVER_ID)
    if guild is None:
        return

    сейчас = datetime.now(timezone.utc)

    роли = db.execute(
        "SELECT member_id, role_id, expires_at, preexisting "
        "FROM shop_role_expirations"
    ).fetchall()

    for member_id, role_id, expires_at, preexisting in роли:
        if datetime.fromisoformat(expires_at) > сейчас:
            continue

        try:
            member = await guild.fetch_member(member_id)
        except discord.NotFound:
            db.execute(
                "DELETE FROM shop_role_expirations WHERE member_id = ? AND role_id = ?",
                (member_id, role_id),
            )
            db.commit()
            continue
        except discord.HTTPException:
            continue

        role = guild.get_role(role_id)
        try:
            if role and not preexisting and role in member.roles:
                await member.remove_roles(role, reason="Истёк срок покупки роли")
        except (discord.Forbidden, discord.HTTPException):
            continue

        db.execute(
            "DELETE FROM shop_role_expirations WHERE member_id = ? AND role_id = ?",
            (member_id, role_id),
        )
        db.commit()

    vip_rows = db.execute(
        "SELECT member_id, expires_at, had_overwrite, previous_overwrite "
        "FROM shop_vip_access"
    ).fetchall()

    vip_channel = guild.get_channel(VIP_CHANNEL_ID)

    for member_id, expires_at, had_overwrite, previous_overwrite in vip_rows:
        if datetime.fromisoformat(expires_at) > сейчас:
            continue

        if vip_channel is None:
            continue

        try:
            member = await guild.fetch_member(member_id)
        except discord.NotFound:
            db.execute("DELETE FROM shop_vip_access WHERE member_id = ?", (member_id,))
            db.commit()
            continue
        except discord.HTTPException:
            continue

        try:
            if had_overwrite and previous_overwrite:
                overwrite = discord.PermissionOverwrite(
                    **json.loads(previous_overwrite)
                )
            else:
                overwrite = None

            await vip_channel.set_permissions(
                member,
                overwrite=overwrite,
                reason="Истёк срок VIP-доступа",
            )
        except (discord.Forbidden, discord.HTTPException):
            continue

        db.execute("DELETE FROM shop_vip_access WHERE member_id = ?", (member_id,))
        db.commit()
        await log_action(
            guild,
            f"Истёк VIP-доступ участника {member.mention}; персональные права восстановлены.",
        )

class ПодтверждениеЗаказа(discord.ui.View):
    def __init__(self, владелец_id: int, ключ: str, срок: int):
        super().__init__(timeout=180)
        self.владелец_id = владелец_id
        self.ключ = ключ
        self.срок = срок

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.владелец_id:
            await interaction.response.send_message(
                "Это меню открыто не тобой.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Подтвердить и купить",
        emoji="🛒",
        style=discord.ButtonStyle.success,
    )
    async def подтвердить(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.defer()
        результат = await оформить_покупку(
            interaction,
            self.ключ,
            self.срок,
        )
        await interaction.edit_original_response(
            content=результат,
            embed=None,
            view=None,
        )

    @discord.ui.button(
        label="Отмена",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def отменить(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            content="Покупка отменена. Баллы не списаны.",
            embed=None,
            view=None,
        )



@bot.tree.command(
    name="каталог",
    description="Открыть интерактивный каталог магазина",
    guild=SERVER,
)
async def каталог(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    карточка = discord.Embed(
        title="⛩️ Магазин Yotiko",
        description=(
            "Выбери товар в меню ниже. Затем можно будет выбрать срок "
            "и проверить стоимость."
        ),
        color=discord.Color.from_rgb(128, 0, 128),
    )
    карточка.add_field(
        name="👑 Роли",
        value=(
            "<@&1572265083323809792> — 10 000 баллов/мес.\n"
            "<@&1572266098890514462> — 5 000 баллов/мес.\n"
            "<@&1572266490366001245> — 2 500 баллов/мес."
        ),
        inline=False,
    )
    карточка.add_field(
        name="🔐 VIP-комната",
        value="2 000 баллов за каждые 14 дней.",
        inline=True,
    )
    карточка.add_field(
        name="💎 Discord Nitro",
        value="15 000 баллов; ожидание выдачи — до 12 часов.",
        inline=True,
    )

    await interaction.response.send_message(
        embed=карточка,
        view=КаталогБаллов(interaction.user.id),
        ephemeral=True,
    )

@bot.listen("on_interaction")
async def проверить_взаимодействие(interaction: discord.Interaction):
    print(
        f"[INTERACTION] сервер={interaction.guild_id}, "
        f"тип={interaction.type}, "
        f"команда={getattr(interaction.command, 'name', None)}"
    )


VOICE_EXCLUDED_CHANNEL_ID = 1540772710806855831


@tasks.loop(seconds=15)
async def начислять_голосовые_баллы():
    guild = bot.get_guild(SERVER_ID)
    if guild is None:
        return

    сейчас = datetime.now(timezone.utc)
    участники_в_войсе = {}

    все_войсы = list(guild.voice_channels) + list(guild.stage_channels)

    for канал in все_войсы:
        if канал.id == VOICE_EXCLUDED_CHANNEL_ID:
            continue

        for участник in канал.members:
            if not участник.bot:
                участники_в_войсе[участник.id] = участник

    активные_id = set(участники_в_войсе)

    # Если участник вышел из войса или перешёл в исключённый канал,
    # сбрасываем текущую сессию. Накопленные 4-часовые баллы сохраняются.
    отслеживаемые = db.execute(
        "SELECT member_id FROM voice_point_progress WHERE last_tick_at IS NOT NULL"
    ).fetchall()

    for (member_id,) in отслеживаемые:
        if member_id not in активные_id:
            db.execute(
                "UPDATE voice_point_progress "
                "SET session_seconds = 0, last_tick_at = NULL "
                "WHERE member_id = ?",
                (member_id,),
            )

    for member_id in активные_id:
        db.execute(
            "INSERT OR IGNORE INTO voice_point_progress (member_id) VALUES (?)",
            (member_id,),
        )

        строка = db.execute(
            "SELECT activity_seconds, session_seconds, "
            "last_tick_at, last_daily_reward_at "
            "FROM voice_point_progress WHERE member_id = ?",
            (member_id,),
        ).fetchone()

        activity_seconds, session_seconds, last_tick_at, last_daily = строка

        # Первый проход только начинает отсчёт — время до запуска бота
        # или до первого прохода не засчитывается.
        if last_tick_at is None:
            db.execute(
                "UPDATE voice_point_progress SET last_tick_at = ? "
                "WHERE member_id = ?",
                (сейчас.isoformat(), member_id),
            )
            continue

        прошло = (
            сейчас - datetime.fromisoformat(last_tick_at)
        ).total_seconds()

        # Не засчитываем большой промежуток, если бот завис или был отключён.
        прошло = max(0.0, min(30.0, прошло))

        activity_seconds += прошло
        session_seconds += прошло

        начислено = 0

        # 50 баллов за 5 минут подряд, не чаще одного раза за 24 часа.
        прошло_24_часа = (
            last_daily is None
            or сейчас - datetime.fromisoformat(last_daily) >= timedelta(hours=24)
        )

        if session_seconds >= 300 and прошло_24_часа:
            начислено += 50
            session_seconds = 0
            last_daily = сейчас.isoformat()

        # 10 баллов за каждые полные 4 часа; остаток остаётся на будущее.
        полные_четыре_часа = int(activity_seconds // 14400)
        if полные_четыре_часа:
            начислено += полные_четыре_часа * 10
            activity_seconds -= полные_четыре_часа * 14400

        db.execute(
            "UPDATE voice_point_progress "
            "SET activity_seconds = ?, session_seconds = ?, "
            "last_tick_at = ?, last_daily_reward_at = ? "
            "WHERE member_id = ?",
            (
                activity_seconds,
                session_seconds,
                сейчас.isoformat(),
                last_daily,
                member_id,
            ),
        )

        if начислено:
            db.execute(
                "INSERT OR IGNORE INTO point_balances (member_id, balance) "
                "VALUES (?, 0)",
                (member_id,),
            )
            db.execute(
                "UPDATE point_balances SET balance = balance + ? "
                "WHERE member_id = ?",
                (начислено, member_id),
            )

    db.commit()

DAILY_REWARD_CHANNEL_ID = 1540951771776553011
DAILY_MESSAGE_REWARD = 20


@bot.listen("on_message")
async def награда_за_сообщение(message: discord.Message):
    if message.guild is None or message.guild.id != SERVER_ID:
        return

    if message.channel.id != DAILY_REWARD_CHANNEL_ID:
        return

    if message.author.bot or message.webhook_id is not None:
        return

    сейчас = datetime.now(timezone.utc)

    строка = db.execute(
        "SELECT last_reward_at FROM daily_chat_rewards WHERE member_id = ?",
        (message.author.id,),
    ).fetchone()

    if строка:
        последнее_начисление = datetime.fromisoformat(строка[0])
        if сейчас - последнее_начисление < timedelta(hours=24):
            return

    db.execute(
        "INSERT OR IGNORE INTO point_balances (member_id, balance) "
        "VALUES (?, 0)",
        (message.author.id,),
    )
    db.execute(
        """
        INSERT INTO daily_chat_rewards (member_id, last_reward_at)
        VALUES (?, ?)
        ON CONFLICT(member_id)
        DO UPDATE SET last_reward_at = excluded.last_reward_at
        """,
        (message.author.id, сейчас.isoformat()),
    )
    db.execute(
        "UPDATE point_balances SET balance = balance + ? WHERE member_id = ?",
        (DAILY_MESSAGE_REWARD, message.author.id),
    )
    db.commit()

if not TOKEN:

    raise RuntimeError("Не найден токен в файле .env")

@bot.tree.command(
    name="самые_богатые",
    description="Показать 15 участников с наибольшим количеством баллов",
    guild=SERVER,
)
async def самые_богатые(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Команда доступна только на сервере.",
            ephemeral=True,
        )

    await interaction.response.defer(thinking=True)

    try:
        участники = []

        async for участник in interaction.guild.fetch_members(limit=None):
            if not участник.bot:
                участники.append(участник)

    except discord.Forbidden:
        return await interaction.followup.send(
            "Бот не смог получить список участников. Проверь Server Members Intent "
            "в Discord Developer Portal.",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            "Не удалось загрузить список участников. Попробуй позже.",
            ephemeral=True,
        )

    балансы = dict(
        db.execute(
            "SELECT member_id, balance FROM point_balances"
        ).fetchall()
    )

    участники.sort(
        key=lambda участник: (
            -балансы.get(участник.id, 0),
            участник.display_name.casefold(),
            участник.id,
        )
    )

    топ = участники[:15]

    if not топ:
        return await interaction.followup.send(
            "На сервере пока нет участников для рейтинга."
        )

    строки = []
    for место, участник in enumerate(топ, start=1):
        баллы = балансы.get(участник.id, 0)
        строки.append(
            f"**{место}.** {участник.mention} — **{баллы:,} баллов**"
        )

    карточка = discord.Embed(
        title="🏆 Самые богатые участники",
        description="\n".join(строки),
        color=discord.Color.from_rgb(128, 0, 128),
    )

    await interaction.followup.send(embed=карточка)

bot.run(TOKEN)
