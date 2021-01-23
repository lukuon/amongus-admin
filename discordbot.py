import os
import logging
from enum import Enum
from typing import Dict, Set, Optional

from discord import Client, Member, TextChannel, VoiceChannel, Message, Guild, User, VoiceState, DMChannel
import dotenv

logger = logging.getLogger("amongus_admin")

dotenv.load_dotenv(".env")
client = Client()

bot_prefix = "/amongus "
separator = "-" * 20 + "\n"


class Localized:
    lobby = "lobby"
    emergency = "emergency"
    mute = "mute"
    graveyard = "graveyard"
    help_message = f"Hi! I'm AmongUs Admin bot. To start a AmongUs session, type `{bot_prefix}create`."
    error_message = "Oops, wrong command."
    no_guild = "First, start or join a AmongUs session in a single Server!"
    locale_set_message = "The Locale for the server is now: English"
    new_session = (
        "There's a new AmongUs session: `{session_id}`!\n"
        "Go to the lobby voice channel of the session to join the session!"
    )
    create_message = (
        "Hi {name}! You created an AmongUs session: {session_id}.\n"
        f"When ready, type `{bot_prefix}start` to start the session!"
    )
    join_message = "Hi {name}! You joined an AmongUs session: {session_id}."
    start_message_admin = f"`{bot_prefix}gather` to start a emergency meeting, and `{bot_prefix}mute` to end it!"
    start_message = "Session {session_id} started!\n" f"`{bot_prefix}dead` to tell me when you're ejected or dead"
    dead_message = "(Oh no! I'll put you in the dead list then. Join the other party now...)"


class Japanese(Localized):
    lobby = "ロビー"
    emergency = "緊急会議"
    mute = "ミュート"
    graveyard = "墓地"
    help_message = f"こんにちは！AmongUs Adminボットです。AmongUsのセッションを作成するには、`{bot_prefix}create`とタイプしてください！"
    error_message = "すみません、、わからないコマンドです。。"
    no_guild = "まず、どこかのサーバーでAmongUsのセッションを開始または参加してください！"
    locale_set_message = "サーバーの言語が変更されました！: 日本語"
    new_session = "新しいAmongUsのセッション({session_id})が作成されました!\n" "参加したい人はロビーのボイスチャンネルに入ってください！"
    create_message = "{name}やっほー! AmongUsのセッションを作成しました！: {session_id}\n" f"準備ができたら`{bot_prefix}start`でセッションを開始してください！"
    join_message = "{name}やっほー! AmongUsのセッションに参加しました！: {session_id}\n"
    start_message_admin = f"`{bot_prefix}gather`で会議開始、`{bot_prefix}mute`で会議終了です。"
    start_message = "{session_id}が開始されました！\n" f"追放されたり誰かに殺されたら、`{bot_prefix}dead`で教えてください！"
    dead_message = "(おおっと！そうしたら死亡者リストに登録しますね！こっち側も楽しいですよ。。)"


async def try_edit(member: Member, vc: Optional[VoiceChannel], mute: bool, deafen: bool):
    logger.debug(
        f"try edit {member.display_name} @ {member.guild.name}"
        f" -> vc: {vc and vc.name} mute: {mute} deafen: {deafen}"
    )
    voice_state: VoiceState = member.voice
    if not voice_state or not voice_state.channel:
        return
    if voice_state.channel == vc:
        return
    await member.edit(voice_channel=vc, mute=mute, deafen=deafen)


class AmongUsSessionStatus(Enum):
    ALIVE = 0
    DEAD = 1


class AmongUsSession:
    admin: Member
    members: Set[Member]
    lobby: Optional[VoiceChannel]
    emergency: Optional[VoiceChannel]
    mute: Optional[VoiceChannel]
    graveyard: Optional[VoiceChannel]
    manager: "AmongUsSessionManager"
    status: Dict[Member, AmongUsSessionStatus]
    deleting: bool

    def __init__(self, session_id: str, admin: Member, manager: "AmongUsSessionManager"):
        self.id = session_id
        self.admin = admin
        self.manager = manager
        self.members = set()
        self.status = {}
        self.lobby = None
        self.emergency = None
        self.mute = None
        self.graveyard = None
        self.deleting = False
        logger.info(f"New Session: {self.id} @ {self.manager.guild.name}")

    @classmethod
    async def create(cls, session_id: str, admin: Member, channel: TextChannel, manager: "AmongUsSessionManager"):
        ins = cls(session_id, admin, manager)
        ins.lobby = await ins.manager.guild.create_voice_channel(f"{ins.manager.locale.lobby}-{ins.id}")
        ins.members.add(admin)
        ins.status = {admin: AmongUsSessionStatus.ALIVE}
        await admin.send(
            separator + ins.manager.locale.create_message.format(name=admin.display_name, session_id=ins.id),
            mention_author=True,
        )
        await channel.send(ins.manager.locale.new_session.format(session_id=session_id))
        await try_edit(admin, vc=ins.lobby, mute=False, deafen=False)
        return ins

    async def join(self, new_member: Member):
        if self.deleting or new_member in self.members:
            return
        logger.info(f"{new_member.display_name} joined session: {self.id} @ {self.manager.guild.name}")
        self.members.add(new_member)
        self.status[new_member] = AmongUsSessionStatus.ALIVE
        await try_edit(new_member, vc=self.lobby, mute=False, deafen=False)
        await new_member.send(
            separator + self.manager.locale.join_message.format(name=new_member.display_name, session_id=self.id),
            mention_author=True,
        )

    async def leave(self, a_member: Member):
        if self.deleting or a_member not in self.members:
            return
        logger.info(f"{a_member.display_name} left session: {self.id} @ {self.manager.guild.name}")
        await try_edit(a_member, vc=None, mute=False, deafen=False)
        self.members.remove(a_member)
        del self.status[a_member]

    async def dead(self, a_member: Member):
        if self.deleting or a_member not in self.members:
            return
        logger.info(f"{a_member.display_name} is dead: {self.id} @ {self.manager.guild.name}")
        self.status[a_member] = AmongUsSessionStatus.DEAD
        await a_member.send(self.manager.locale.dead_message)

    async def end_emergency(self, member: Member):
        if self.deleting or member != self.admin:
            return
        logger.info(f"end emergency: {self.id} @ {self.manager.guild.name}")
        for member in self.members:
            if self.status[member] == AmongUsSessionStatus.ALIVE:
                await try_edit(member, vc=self.mute, mute=True, deafen=True)
            if self.status[member] == AmongUsSessionStatus.DEAD:
                await try_edit(member, vc=self.graveyard, mute=False, deafen=False)

    async def declare_emergency(self, member: Member):
        if self.deleting or member != self.admin:
            return
        logger.info(f"declare emergency: {self.id} @ {self.manager.guild.name}")
        for member in self.members:
            await try_edit(
                member, vc=self.emergency, mute=self.status[member] == AmongUsSessionStatus.DEAD, deafen=False
            )

    async def start(self, member: Member):
        if self.deleting or member != self.admin:
            return
        admin = member
        logger.info(f"start session: {self.id} @ {self.manager.guild.name}")
        for member in self.members:
            self.status[member] = AmongUsSessionStatus.ALIVE
            await member.send(separator + self.manager.locale.start_message.format(session_id=self.id))
        await self.admin.send(self.manager.locale.start_message_admin.format(session_id=self.id))
        self.mute = await self.manager.guild.create_voice_channel(f"{self.manager.locale.mute}-{self.id}")
        self.emergency = await self.manager.guild.create_voice_channel(f"{self.manager.locale.emergency}-{self.id}")
        self.graveyard = await self.manager.guild.create_voice_channel(f"{self.manager.locale.graveyard}-{self.id}")
        await self.end_emergency(admin)
        self.lobby = await self.lobby.delete()

    async def end(self, member: Member):
        if self.deleting or member != self.admin:
            return
        logger.info(f"end session: {self.id} @ {self.manager.guild.name}")
        self.lobby = await self.manager.guild.create_voice_channel(f"{self.manager.locale.lobby}-{self.id}")
        for member in self.members:
            await try_edit(member, vc=self.lobby, mute=False, deafen=False)
        self.mute = await self.mute.delete()
        self.emergency = await self.emergency.delete()
        self.graveyard = await self.graveyard.delete()
        for member in self.members:
            dm: DMChannel = await member.create_dm()
            async for message in dm.history():  # type: Message
                if message.author == client.user:
                    await message.delete()

    async def close(self, member: Member):
        if member != self.admin:
            return
        logger.info(f"close session: {self.id} @ {self.manager.guild.name}")
        self.deleting = True
        for member in self.members:
            await try_edit(member, vc=None, mute=False, deafen=False)
        self.lobby = self.lobby and await self.lobby.delete()
        self.mute = self.mute and await self.mute.delete()
        self.emergency = self.emergency and await self.emergency.delete()
        self.graveyard = self.graveyard and await self.graveyard.delete()


class AmongUsSessionManager:
    session_prefix: str = "AmongUs"
    guild: Guild
    locale: Localized
    sessions: Dict[str, AmongUsSession]
    member_sessions_idx: Dict[Member, str]

    def __init__(self, guild: Guild, session_prefix=None):
        logger.info(f"New Guild: {guild.name} ({guild.id})")
        self.guild = guild
        self.locale = Localized()
        self.sessions = {}
        self.session_prefix = session_prefix or self.session_prefix
        self.member_sessions_idx = {}

    def set_locale(self, locale):
        if locale in ("ja_JP", "japanese", "日本語"):
            self.locale = Japanese()
        else:
            self.locale = Localized()

    async def create_session(self, author: Member, channel: TextChannel):
        count = len(self.sessions)
        session_id = f"{self.session_prefix}-{count + 1}"
        session = await AmongUsSession.create(session_id, author, channel, self)
        self.member_sessions_idx[author] = session_id
        self.sessions[session_id] = session

    async def close_session(self, admin: Member):
        session_id = self.member_sessions_idx.get(admin)
        if not session_id:
            return
        session = self.sessions[session_id]
        if session.admin != admin:
            return
        await session.close(admin)
        for member in session.members:
            if member in self.member_sessions_idx:
                del self.member_sessions_idx[member]
        del self.sessions[session_id]


managers: Dict[Guild, AmongUsSessionManager] = {}


# 起動時に動作する処理
@client.event
async def on_ready():
    # 起動したらターミナルにログイン通知が表示される
    logger.info("ログインしました")


# メッセージ受信時に動作する処理
@client.event
async def on_message(message: Message):
    # メッセージ送信者がBotだった場合は無視する
    if message.author.bot or not message.content.startswith(bot_prefix):
        return
    command, *args = message.content.split(bot_prefix)[1].split(" ")
    logger.debug(f"{command=}, {args=}")
    guild: Optional[Guild] = message.guild
    manager: Optional[AmongUsSessionManager] = None
    if not guild:
        user: User = message.author
        for _guild, _manager in managers.items():
            if user in _manager.member_sessions_idx:
                guild, manager = _guild, _manager
                break
    else:
        if guild not in managers:
            managers[guild] = AmongUsSessionManager(guild)
        manager = managers[guild]
    if not manager:
        await message.channel.send(Localized.no_guild)
        return
    session = manager.sessions.get(manager.member_sessions_idx.get(message.author))
    if command == "help":
        await message.channel.send(manager.locale.help_message)
    elif command == "create":
        await manager.create_session(message.author, message.channel)
    elif command == "close":
        await manager.close_session(message.author)
    elif command == "start" and session:
        await session.start(message.author)
    elif command == "end" and session:
        await session.end(message.author)
    elif command == "gather" and session:
        await session.declare_emergency(message.author)
    elif command == "mute" and session:
        await session.end_emergency(message.author)
    elif command == "dead" and session:
        await session.dead(message.author)
    elif command == "locale":
        if not args:
            await message.channel.send(manager.locale.error_message)
            return
        manager.set_locale(args[0])
        await message.channel.send(manager.locale.locale_set_message)
    else:
        await message.channel.send(manager.locale.error_message)


# VoiceState変更フック
@client.event
async def on_voice_state_update(member: Member, before: VoiceState, after: VoiceState):
    lobbies: Dict[VoiceChannel, AmongUsSession] = {}
    for manager in managers.values():
        for session in manager.sessions.values():
            if session.lobby:
                lobbies[session.lobby] = session
    if after.channel and after.channel in lobbies:
        session = lobbies[after.channel]
        manager = session.manager
        if member in manager.member_sessions_idx:
            session_before = manager.sessions[manager.member_sessions_idx[member]]
            if session_before != session:
                await session_before.leave(member)
        await session.join(member)
        session.manager.member_sessions_idx[member] = session.id
    if before.channel and before.channel in lobbies and after.channel is None:
        before_session = lobbies[before.channel]
        await before_session.leave(member)
        if member in before_session.manager.member_sessions_idx:
            del before_session.manager.member_sessions_idx[member]


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:\t[%(name)s]\t%(message)s")
    client.run(os.environ["DISCORD_BOT_TOKEN"])
