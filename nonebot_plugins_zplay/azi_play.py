from nonebot import require, get_driver
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import Message, GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11.event import Event
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import on_command
from nonebot.typing import Union
import nonebot
from nonebot_plugin_guild_patch import GuildMessageEvent  # DO NOT DELETE

from .plugins.zplay.deal_event import zplay, zplay_tool
from .plugins.zplay.obs_websocket import OBS_PLAY
from .plugins.zplay.sql_redis import insert_redis
from .config_zplay import obs_config

try:
    master = get_driver().config.master
except:
    master = []

live_channel = obs_config['live_channel']
call_channel = obs_config['call_channel']
live_guild = obs_config['live_guild']
set_expired_time = obs_config['set_expired_time']


async def rule_check_guild(event: Union[Event, GroupMessageEvent, GuildMessageEvent, PrivateMessageEvent]) -> bool:
    return event.message_type == 'guild'


async def rule_check_user(user_id,
                          event: Union[Event, GroupMessageEvent, GuildMessageEvent, PrivateMessageEvent]) -> bool:
    return event.user_id == user_id


async def rule_check_channel(event: Union[GuildMessageEvent]) -> bool:
    return str(event.channel_id) == call_channel


async def rule_check_player(event: Union[Event, GuildMessageEvent]) -> bool:
    return event.message != '点播'


rule_player = Rule(rule_check_player, rule_check_guild, rule_check_channel)

scheduler = require('nonebot_plugin_apscheduler').scheduler
ow = OBS_PLAY()
sql = insert_redis()

matcher_select_player = on_command('点播', rule=rule_player, priority=5)
matcher_get_list = on_command('播放列表', aliases={'zlist'}, rule=rule_player, priority=5)


@matcher_select_player.handle()
async def select_player(matcher: Matcher, event: Union[Event, GuildMessageEvent, PrivateMessageEvent],
                        arg: Message = CommandArg()):
    arg = arg.extract_plain_text().strip()
    if not arg:
        await matcher_select_player.finish()
    z = zplay(event, arg)
    data = await z.song_select()
    if data['code'] == 200:
        await matcher_select_player.finish(data["message"])
        matcher.stop_propagation()
    elif data['code'] == 400:
        await matcher_select_player.finish(data["message"])
        matcher.stop_propagation()
    elif data['code'] == 300:
        await matcher_select_player.send(f'输入数字进行选取, 有效时间为{set_expired_time}秒\n' + data["message"])
        await matcher_select_player.pause()


@matcher_select_player.handle()
async def select_player(event: Union[Event, GuildMessageEvent, PrivateMessageEvent]):
    seq = await sql.temp_get(str(event.user_id))
    u_seq = event.get_plaintext()
    if seq:
        if u_seq in seq:
            await sql.list_add(seq[u_seq], str(event.user_id))
            await matcher_select_player.finish(f"已为您将'{seq[u_seq]['song_name']}'添加至播放列表")
        else:
            await matcher_select_player.reject('超出索引范围，请重试')
    else:
        await matcher_select_player.finish()


@matcher_get_list.handle()
async def get_list():
    seq = await sql.list_all()
    seq = zplay_tool.insert_num(seq)
    seq = '\n'.join(seq) if any(seq) else '暂无点播, 目前为随机播放'
    now_play = await sql.play_now()
    await matcher_get_list.finish(f'当前正在播放: {now_play}\n待播放列表:\n{seq}')


@scheduler.scheduled_job('interval', seconds=5, id='live_sched', misfire_grace_time=60)
async def timer_obs():
    bot = nonebot.get_bots().values()
    event: Event
    result = ow.obs_ws.get_media_input_status(ow.media)
    if result.media_state == 'OBS_MEDIA_STATE_ENDED':
        song_data = await sql.list_to_play()
        await ow.obs_change(song_data[0]) if song_data else \
            await ow.obs_change(await ow.random_select())
        if song_data:
            await bot.call_api("send_guild_channel_msg", **{
                'guild_id': live_guild,
                'channel_id': call_channel,
                'message': Message(f'[CQ:at,qq={song_data[1]}]您预约的{song_data[2]}即将播放')
            })
