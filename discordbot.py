import asyncio
import os
import logging
from enum import Enum
from typing import Dict, Set, Optional

from discord import (
    Member,
    TextChannel,
    VoiceChannel,
    Message,
    Guild,
    User,
    VoiceState,
    RawReactionActionEvent,
)
import dotenv
from discord.ext.commands import Context, Bot

from localized import Localized, English, Japanese

logger = logging.getLogger("amongus_admin")

dotenv.load_dotenv(".env")
prefix = "/"
bot = Bot(command_prefix=prefix)


async def async_nop():
    return


class ActionReaction(str, Enum):
    START = "▶️"
    STOP = "⏹"
    CLOSE = "❌"
    DEAD = "☠️"
    GATHER = "📢"
    MUTE = "🔇"


class AmongUsSessionStatus(int, Enum):
    ALIVE = 0
    DEAD = 1


class AmongUsSession:
    admin: Member
    members: Set[Member]
    member_messages: Dict[Member, Message]
    reaction_messages: Dict[Member, Message]
    lobby: Optional[VoiceChannel]
    emergency: Optional[VoiceChannel]
    mute: Optional[VoiceChannel]
    graveyard: Optional[VoiceChannel]
    manager: "AmongUsSessionManager"
    status: Dict[Member, AmongUsSessionStatus]
    started: bool
    is_emergency: bool
    deleting: bool

    def __init__(self, session_id: str, admin: Member, manager: "AmongUsSessionManager"):
        self.id = session_id
        self.admin = admin
        self.manager = manager
        self.members = set()
        self.member_messages = {}
        self.reaction_messages = {}
        self.status = {}
        self.lobby = None
        self.emergency = None
        self.mute = None
        self.graveyard = None
        self.started = False
        self.is_emergency = False
        self.deleting = False
        logger.info(f"New Session: {self.id} @ {self.manager.guild.name}")

    async def set_private_message(self, member: Member):
        """
        set Member's private message

        :param member:
        :return:
        """
        messages = []
        reactions = set()
        is_admin = self.admin == member
        if self.deleting or (member not in self.members and member in self.member_messages):
            message_to_delete = self.member_messages[member]
            reaction_to_delete = self.reaction_messages[member]
            del self.member_messages[member]
            del self.reaction_messages[member]
            await message_to_delete.delete()
            await reaction_to_delete.delete()
        else:
            header_message = self.manager.locale.create_message if is_admin else self.manager.locale.join_message
            messages.append(header_message.format(name=member.display_name, session_id=self.id))
            if not self.started and is_admin:
                messages.append(self.manager.locale.ready_message)
                reactions.add(ActionReaction.START)
                reactions.add(ActionReaction.CLOSE)
            if self.started:
                messages.append(self.manager.locale.start_message.format(session_id=self.id))
                if is_admin:
                    messages.append(self.manager.locale.start_message_admin)
                    reactions.add(ActionReaction.MUTE if self.is_emergency else ActionReaction.GATHER)
                    reactions.add(ActionReaction.STOP)
                if self.status[member] == AmongUsSessionStatus.DEAD:
                    messages.append(self.manager.locale.dead_message)
                else:
                    reactions.add(ActionReaction.DEAD)

            async def inner():
                target_message = "\n".join(messages)
                if member not in self.member_messages:
                    self.member_messages[member] = await member.send(target_message)
                else:
                    self.member_messages[member] = await member.fetch_message(self.member_messages[member].id)
                if member not in self.reaction_messages:
                    self.reaction_messages[member] = await member.send(self.manager.locale.controls)
                else:
                    self.reaction_messages[member] = await member.fetch_message(self.reaction_messages[member].id)
                    for reaction in self.reaction_messages[member].reactions:
                        if reaction.count > 1:
                            await self.reaction_messages[member].delete()
                            self.reaction_messages[member] = await member.send(self.manager.locale.controls)
                            break
                inner_tasks = []
                for reaction in self.reaction_messages[member].reactions:
                    if reaction.emoji in reactions:
                        reactions.remove(reaction.emoji)
                    else:
                        inner_tasks.append(reaction.remove(bot.user))

                if reactions:

                    async def add_reactions():
                        for _reaction in reactions:
                            await self.reaction_messages[member].add_reaction(_reaction.value)

                    inner_tasks.append(add_reactions())
                if self.member_messages[member].content != target_message:
                    inner_tasks.append(self.member_messages[member].edit(content=target_message))
                if len(inner_tasks) > 0:
                    await asyncio.gather(*inner_tasks)

            await inner()

    async def prepare_vc(self):
        """
        set Session's vc

        :return:
        """
        tasks = []
        if not self.lobby:

            async def create_lobby():
                self.lobby = await self.manager.guild.create_voice_channel(f"{self.manager.locale.lobby}-{self.id}")

            tasks.append(create_lobby())
        if not self.mute:

            async def create_mute():
                self.mute = await self.manager.guild.create_voice_channel(f"{self.manager.locale.mute}-{self.id}")

            tasks.append(create_mute())
        if not self.emergency:

            async def create_emergency():
                self.emergency = await self.manager.guild.create_voice_channel(
                    f"{self.manager.locale.emergency}-{self.id}"
                )

            tasks.append(create_emergency())
        if not self.graveyard:

            async def create_graveyard():
                self.graveyard = await self.manager.guild.create_voice_channel(
                    f"{self.manager.locale.graveyard}-{self.id}"
                )

            tasks.append(create_graveyard())
        await asyncio.gather(*tasks)

    async def try_edit(self, member: Member, vc: Optional[VoiceChannel], mute: bool, deafen: bool):
        if not hasattr(member, "guild"):
            member = self.manager.guild.get_member(member.id)
        logger.debug(
            f"try edit {member.display_name} @ {member.guild.name}"
            f" -> vc: {vc and vc.name} mute: {mute} deafen: {deafen}"
        )
        target_voice = VoiceState(data=dict(mute=mute, deafen=deafen), channel=vc)
        voice_state: VoiceState = member.voice
        if not voice_state or not voice_state.channel:
            return
        if voice_state == target_voice:
            return
        await asyncio.create_task(
            member.edit(voice_channel=target_voice.channel, mute=target_voice.mute, deafen=target_voice.deaf)
        )

    async def set_vc(self, member: Member):
        """
        set Member's channel

        :param member:
        :return:
        """
        if self.deleting:
            await self.try_edit(member, vc=None, mute=False, deafen=False)
        else:
            if not self.started:
                await self.try_edit(member, vc=self.lobby, mute=False, deafen=False)
            else:
                if self.is_emergency:
                    await self.try_edit(
                        member, vc=self.emergency, mute=self.status[member] == AmongUsSessionStatus.DEAD, deafen=False
                    )
                else:
                    if self.status[member] == AmongUsSessionStatus.ALIVE:
                        await self.try_edit(member, vc=self.mute, mute=True, deafen=True)
                    if self.status[member] == AmongUsSessionStatus.DEAD:
                        await self.try_edit(member, vc=self.graveyard, mute=False, deafen=False)

    async def clean_vc(self):
        """
        clean Session's vc

        :return:
        """
        tasks = []
        if self.lobby and (self.started or self.deleting):

            async def delete_lobby():
                self.lobby = await self.lobby.delete()

            tasks.append(delete_lobby())
        if self.mute and (not self.started or self.deleting):

            async def delete_mute():
                self.mute = await self.mute.delete()

            tasks.append(delete_mute())
        if self.emergency and (not self.started or self.deleting):

            async def delete_emergency():
                self.emergency = await self.emergency.delete()

            tasks.append(delete_emergency())
        if self.graveyard and (not self.started or self.deleting):

            async def delete_graveyard():
                self.graveyard = await self.graveyard.delete()

            tasks.append(delete_graveyard())
        await asyncio.gather(*tasks)

    async def set_interface(self, prepare_vc=True):
        async def vc_task():
            if prepare_vc:
                await self.prepare_vc()
            tasks = []
            for member in self.members:
                tasks.append(self.set_vc(member))
            await asyncio.gather(*tasks)
            await self.clean_vc()

        async def message_task():
            tasks = []
            for member in self.members:
                tasks.append(self.set_private_message(member))
            await asyncio.gather(*tasks)

        await asyncio.gather(vc_task(), message_task())

    @classmethod
    async def create(cls, session_id: str, admin: Member, channel: TextChannel, manager: "AmongUsSessionManager"):
        ins = cls(session_id, admin, manager)
        ins.members.add(admin)
        ins.status = {admin: AmongUsSessionStatus.ALIVE}

        async def interface_init():
            ins.lobby = await ins.manager.guild.create_voice_channel(f"{ins.manager.locale.lobby}-{ins.id}")
            await ins.set_interface(prepare_vc=False)

        async def public_message():
            await channel.send(ins.manager.locale.new_session.format(session_id=session_id))

        asyncio.create_task(interface_init())
        asyncio.create_task(public_message())
        return ins

    async def join(self, new_member: Member):
        if self.deleting or new_member in self.members:
            return
        logger.info(f"{new_member.display_name} joined session: {self.id} @ {self.manager.guild.name}")
        self.members.add(new_member)
        self.manager.member_sessions_idx[new_member] = self.id
        self.status[new_member] = AmongUsSessionStatus.ALIVE
        asyncio.create_task(self.set_interface())

    async def leave(self, a_member: Member):
        if self.deleting or a_member not in self.members:
            return
        logger.info(f"{a_member.display_name} left session: {self.id} @ {self.manager.guild.name}")
        if a_member == self.admin:
            return await self.manager.close_session(a_member)
        if a_member in self.members:
            self.members.remove(a_member)
        if a_member in self.status:
            del self.status[a_member]
        if self.manager.member_sessions_idx.get(a_member) == self.id:
            del self.manager.member_sessions_idx[a_member]
        asyncio.create_task(self.set_interface())

    async def dead(self, a_member: Member):
        if self.deleting or a_member not in self.members or self.status[a_member] == AmongUsSessionStatus.DEAD:
            return
        logger.info(f"{a_member.display_name} is dead: {self.id} @ {self.manager.guild.name}")
        self.status[a_member] = AmongUsSessionStatus.DEAD
        if self.is_emergency:
            asyncio.create_task(self.set_vc(a_member))
        asyncio.create_task(self.set_private_message(a_member))

    async def end_emergency(self, member: Member, prepare_vc=False):
        if self.deleting or member != self.admin:
            return
        self.is_emergency = False
        logger.info(f"end emergency: {self.id} @ {self.manager.guild.name}")
        asyncio.create_task(self.set_interface(prepare_vc))

    async def declare_emergency(self, member: Member):
        if self.deleting or member != self.admin or self.is_emergency:
            return
        self.is_emergency = True
        logger.info(f"declare emergency: {self.id} @ {self.manager.guild.name}")
        asyncio.create_task(self.set_interface(prepare_vc=False))

    async def start(self, member: Member):
        if self.deleting or member != self.admin or self.started:
            return
        self.started = True
        admin = member
        logger.info(f"start session: {self.id} @ {self.manager.guild.name}")
        await self.end_emergency(admin, prepare_vc=True)

    async def end(self, member: Member):
        if self.deleting or member != self.admin or not self.started:
            return
        self.started = False
        logger.info(f"end session: {self.id} @ {self.manager.guild.name}")
        asyncio.create_task(self.set_interface(prepare_vc=True))

    async def close(self, member: Member):
        if member != self.admin:
            return
        logger.info(f"close session: {self.id} @ {self.manager.guild.name}")
        self.deleting = True
        asyncio.create_task(self.set_interface(prepare_vc=False))


class AmongUsSessionManager:
    session_prefix: str = "AmongUs"
    guild: Guild
    locale: Localized
    sessions: Dict[str, AmongUsSession]
    member_sessions_idx: Dict[Member, str]

    def __init__(self, guild: Guild, session_prefix=None):
        logger.info(f"New Guild: {guild.name} ({guild.id})")
        self.guild = guild
        self.locale = English()
        self.sessions = {}
        self.session_prefix = session_prefix or self.session_prefix
        self.member_sessions_idx = {}

    def set_locale(self, locale):
        if locale in ("ja_JP", "japanese", "日本語"):
            self.locale = Japanese()
        else:
            self.locale = English()

    async def create_session(self, author: Member, channel: TextChannel):
        count = len(self.sessions)
        session_id = f"{self.session_prefix}-{count + 1}"
        self.member_sessions_idx[author] = session_id
        self.sessions[session_id] = await AmongUsSession.create(session_id, author, channel, self)

    async def close_session(self, admin: Member):
        session_id = self.member_sessions_idx.get(admin)
        if not session_id:
            return
        session = self.sessions[session_id]
        if session.admin != admin:
            return
        await session.close(admin)
        for member in session.members:
            if self.member_sessions_idx.get(member) == session.id:
                del self.member_sessions_idx[member]
        del self.sessions[session_id]


managers: Dict[Guild, AmongUsSessionManager] = {}
debug = False


# 起動時に動作する処理
@bot.event
async def on_ready():
    # 起動したらターミナルにログイン通知が表示される
    logger.info("ログインしました")
    if debug:
        for channel in bot.get_all_channels():
            if not isinstance(channel, TextChannel):
                continue
            async for message in channel.history(limit=5):
                if message.author.bot:
                    return
                dm = await message.author.create_dm()
                async for _message in dm.history():
                    if _message.author == bot.user:
                        await _message.delete()


@bot.group(invoke_without_command=True)
async def amongus(ctx: Context):
    guild: Optional[Guild] = ctx.guild
    manager: Optional[AmongUsSessionManager] = None
    if not guild:
        user: User = ctx.author
        for _guild, _manager in managers.items():
            if user in _manager.member_sessions_idx:
                guild, manager = _guild, _manager
                break
    else:
        if guild not in managers:
            managers[guild] = AmongUsSessionManager(guild)
        manager = managers[guild]
    if not manager:
        await ctx.send(Localized.no_guild)
        return
    await manager.create_session(ctx.author, ctx.channel)


@amongus.command()
async def setting(ctx: Context, item: Optional[str] = None, new_value: Optional[str] = None):
    guild: Optional[Guild] = ctx.guild
    manager: Optional[AmongUsSessionManager] = None
    if not guild:
        user: User = ctx.author
        for _guild, _manager in managers.items():
            if user in _manager.member_sessions_idx:
                guild, manager = _guild, _manager
                break
    else:
        if guild not in managers:
            managers[guild] = AmongUsSessionManager(guild)
        manager = managers[guild]
    if not manager:
        await ctx.send(Localized.no_guild)
        return
    current_settings = {"locale": manager.locale.__class__.__name__.lower()}
    if not item:
        await ctx.send("\n".join([f"{key}: {value}" for key, value in current_settings.items()]))
        return
    if not new_value:
        await ctx.send(f"{item.lower()}: {current_settings.get(item.lower(), 'Unknown')}")
        return
    if item == "locale":
        manager.set_locale(new_value)
        await ctx.send(manager.locale.locale_set_message)
    else:
        await ctx.send("Unknown setting item")


# VoiceState変更フック
@bot.event
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


# VoiceState変更フック
@bot.event
async def on_raw_reaction_add(event: RawReactionActionEvent):
    if event.emoji.name not in set(ActionReaction):
        return
    for _guild, _manager in managers.items():
        for member, session_id in _manager.member_sessions_idx.items():
            if member.id != event.user_id:
                continue
            session = _manager.sessions[session_id]
            reaction_message = session.reaction_messages[member]
            if reaction_message.id != event.message_id:
                continue
            if event.emoji.name == ActionReaction.START:
                await session.start(member)
            if event.emoji.name == ActionReaction.STOP:
                await session.end(member)
            if event.emoji.name == ActionReaction.CLOSE:
                await _manager.close_session(member)
            if event.emoji.name == ActionReaction.DEAD:
                await session.dead(member)
            if event.emoji.name == ActionReaction.GATHER:
                await session.declare_emergency(member)
            if event.emoji.name == ActionReaction.MUTE:
                await session.end_emergency(member)
            break


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:\t[%(name)s]\t%(message)s")
    bot.run(os.environ["DISCORD_BOT_TOKEN"])
