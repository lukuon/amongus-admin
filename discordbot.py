import asyncio
import os
import logging
from typing import Dict, Set, Optional, List

from discord import (
    Member,
    TextChannel,
    VoiceChannel,
    Message,
    Guild,
    User,
    VoiceState,
    RawReactionActionEvent,
    Permissions,
)
import dotenv
from discord.abc import Messageable
from discord.ext.commands import Context, Bot

from bot_enum import ActionReaction, AmongUsSessionStatus
from localization import Localized, English, Japanese

logger = logging.getLogger("amongus_admin")

dotenv.load_dotenv(".env")
prefix = "/"
bot = Bot(command_prefix=prefix)
base_permissions = Permissions(29568016)
bot_invitation_link = (
    f"https://discord.com/oauth2/authorize?client_id=802513262854799390&permissions="
    f"{base_permissions.value}&scope=bot"
)


async def async_nop():
    return


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
        self.status.update({_member: AmongUsSessionStatus.ALIVE for _member in self.status})
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
    session_counter: List[Optional[str]]
    guild: Guild
    locale: Localized
    sessions: Dict[str, AmongUsSession]
    member_sessions_idx: Dict[Member, str]

    def __init__(self, guild: Guild, session_prefix=None):
        logger.info(f"New Guild: {guild.name} ({guild.id})")
        self.guild = guild
        self.locale = English()
        self.set_locale(guild.preferred_locale)
        self.sessions = {}
        self.session_counter = []
        self.session_prefix = session_prefix or self.session_prefix
        self.member_sessions_idx = {}

    async def check_permissions(self, channel: Messageable, guild: Optional[Guild] = None) -> bool:
        guild: Guild = guild or self.guild
        me: Member = guild.me
        sufficient = base_permissions.is_subset(me.guild_permissions)
        if not sufficient:
            await channel.send(
                self.locale.need_permission_message.format(invitation_link=f"{bot_invitation_link}&guild_id={guild.id}")
            )
        return sufficient

    def set_locale(self, locale):
        if locale in ("ja", "ja_JP", "japanese", "日本語"):
            self.locale = Japanese()
        else:
            self.locale = English()

    async def create_session(self, author: Member, channel: TextChannel):
        if not await self.check_permissions(channel):
            return
        count = len(self.session_counter)
        for i, session_id in enumerate(self.session_counter):
            if session_id is None:
                count = i
        if count < len(self.session_counter):
            self.session_counter[count] = ...  # to prevent other create_session() to take the number
        session_id = f"{self.session_prefix}-{count + 1}"
        self.member_sessions_idx[author] = session_id
        self.sessions[session_id] = await AmongUsSession.create(session_id, author, channel, self)
        if count < len(self.session_counter):
            self.session_counter[count] = session_id
        self.session_counter.append(session_id)

    async def close_session(self, admin: Member):
        if not await self.check_permissions(admin):
            return
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
        for i, _session_id in enumerate(self.session_counter):
            if session_id == _session_id:
                self.session_counter[i] = None
        del self.sessions[session_id]


managers: Dict[Guild, AmongUsSessionManager] = {}


async def get_manager(guild: Optional[Guild], author: User = None) -> Optional[AmongUsSessionManager]:
    guild: Optional[Guild] = guild
    manager: Optional[AmongUsSessionManager] = None
    if not guild:
        user: User = author
        for _guild, _manager in managers.items():
            if user in _manager.member_sessions_idx:
                guild, manager = _guild, _manager
                break
    else:
        manager = managers.get(guild)
        writable_channel = [
            channel for channel in guild.text_channels if channel.permissions_for(guild.me).send_messages
        ]
        target_channel = writable_channel[0]
        if not writable_channel:
            logger.error(f"No writable channel. leaving @ {guild.name}")
            await guild.leave()
        ok: bool
        if not manager:
            manager = managers[guild] = AmongUsSessionManager(guild)
            ok = await manager.check_permissions(target_channel, guild)
        else:
            manager.guild = guild
            ok = await manager.check_permissions(target_channel, guild)
        if not ok:
            logger.error(f"No enough permission. leaving @ {guild.name}")
            await guild.leave()
            del managers[guild]
            return None
    return manager


# 起動時に動作する処理
@bot.event
async def on_ready():
    # 起動したらターミナルにログイン通知が表示される
    logger.info("ログインしました")


@bot.event
async def on_guild_join(guild: Guild):
    manager = await get_manager(guild)
    if manager:
        writable_channel = [
            channel for channel in guild.text_channels if channel.permissions_for(guild.me).send_messages
        ]
        target_channel = writable_channel[0]
        if not writable_channel:
            logger.error(f"No writable channel. leaving @ {guild.name}")
            await guild.leave()
        await target_channel.send(managers[guild].locale.help_message)


@bot.group(invoke_without_command=True)
async def amongus(ctx: Context):
    manager = await get_manager(ctx.guild, ctx.author)
    if not manager:
        await ctx.send(Localized.no_guild)
        return
    await manager.create_session(ctx.author, ctx.channel)


@amongus.command(name="help")
async def help_command(ctx: Context):
    manager = await get_manager(ctx.guild, ctx.author)
    if not manager:
        await ctx.send(Localized.no_guild)
        return
    await ctx.send(manager.locale.help_message)


@amongus.command()
async def setting(ctx: Context, item: Optional[str] = None, new_value: Optional[str] = None):
    manager = await get_manager(ctx.guild, ctx.author)
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
