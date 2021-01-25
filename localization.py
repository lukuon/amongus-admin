from bot_enum import ActionReaction


class Localized:
    lobby = "lobby"
    emergency = "emergency"
    mute = "mute"
    graveyard = "graveyard"
    controls = "[Controls]"
    help_message = f"Hi! I'm AmongUs Admin bot. To start a AmongUs session, type `/amongus`."
    error_message = "Oops, wrong command."
    no_guild = "First, start or join a AmongUs session in a single Server!"
    locale_set_message = "The Locale for the server is now: English"
    new_session = (
        "There's a new AmongUs session: `{session_id}`!\n" "Go to the lobby voice channel of the session to join!"
    )
    create_message = "Hi {name}! You created an AmongUs session: {session_id}."
    ready_message = f"When ready, press `{ActionReaction.START}` to start the session!"
    join_message = "Hi {name}! You joined an AmongUs session: {session_id}."
    start_message_admin = (
        f"Press `{ActionReaction.GATHER}` to start a emergency meeting, and `{ActionReaction.MUTE}` to end it!"
    )
    start_message = (
        "Session {session_id} started!\n" f"Press `{ActionReaction.DEAD}` to tell me when you're ejected or dead"
    )
    dead_message = "(Oh no! I'll put you in the dead list then. Join the other party now...)"


class English(Localized):
    pass


class Japanese(Localized):
    lobby = "ロビー"
    emergency = "緊急会議"
    mute = "ミュート"
    graveyard = "墓地"
    controls = "[ボタン]"
    help_message = f"こんにちは！AmongUs Adminボットです。AmongUsのセッションを作成するには、`/amongus`とタイプしてください！"
    error_message = "すみません、、わからないコマンドです。。"
    no_guild = "まず、どこかのサーバーでAmongUsのセッションを開始または参加してください！"
    locale_set_message = "サーバーの言語が変更されました！: 日本語"
    new_session = "新しいAmongUsのセッション({session_id})が作成されました!\n" "参加したい人はロビーのボイスチャンネルに入ってください！"
    create_message = "{name}やっほー! AmongUsのセッションを作成しました！: {session_id}"
    ready_message = f"準備ができたら`{ActionReaction.START}`を押してセッションを開始してください！"
    join_message = "{name}やっほー! AmongUsのセッションに参加しました！: {session_id}"
    start_message_admin = f"`{ActionReaction.GATHER}`を押して会議開始、`{ActionReaction.MUTE}`を押して会議終了です。"
    start_message = "{session_id}が開始されました！\n" f"追放されたり誰かに殺されたら、`{ActionReaction.DEAD}`を押して教えてください！"
    dead_message = "(おおっと！そうしたら死亡者リストに登録しますね！こっち側も楽しいですよ。。)"
