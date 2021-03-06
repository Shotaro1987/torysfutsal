# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from __future__ import unicode_literals

import datetime
import errno
import json
import os
import sys
import tempfile
from argparse import ArgumentParser

from flask import Flask, request, abort, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    LineBotApiError, InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    SourceUser, SourceGroup, SourceRoom,
    TemplateSendMessage, ConfirmTemplate, MessageAction,
    ButtonsTemplate, ImageCarouselTemplate, ImageCarouselColumn, URIAction,
    PostbackAction, DatetimePickerAction,
    CameraAction, CameraRollAction, LocationAction,
    CarouselTemplate, CarouselColumn, PostbackEvent,
    StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage,
    ImageMessage, VideoMessage, AudioMessage, FileMessage,
    UnfollowEvent, FollowEvent, JoinEvent, LeaveEvent, BeaconEvent,
    MemberJoinedEvent, MemberLeftEvent,
    FlexSendMessage, BubbleContainer, ImageComponent, BoxComponent,
    TextComponent, SpacerComponent, IconComponent, ButtonComponent,
    SeparatorComponent, QuickReply, QuickReplyButton,
    ImageSendMessage)

from httplib2 import Http
from oauth2client.service_account import ServiceAccountCredentials
import apiclient
import dateutil.parser
from dateutil.relativedelta import relativedelta
import locale
import gspread
import sqlite3

#localeを日本にセット
locale.setlocale(locale.LC_TIME, 'ja_JP.UTF-8')

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
    
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

if channel_secret is None:
    logger.error('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

#スケジュール保管用
_events = ''

static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# function for create tmp dir for download content
def make_static_tmp_dir():
    try:
        os.makedirs(static_tmp_path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(static_tmp_path):
            pass
        else:
            raise

#Googleカレンダーから予定を取得
def getSchedule() :
    global _events
    if _events != '' : return _events
    
    ### APIの認証を行う
    # API用の認証JSON
    json_file = './TorysFutsal/client_secret.json'
    # スコープ設定
    scopes = ['https://www.googleapis.com/auth/calendar.readonly']
    # 認証情報作成
    credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scopes)
    http_auth = credentials.authorize(Http())
    # API利用できる状態を作る
    service = apiclient.discovery.build("calendar", "v3", http=http_auth)
    
    # カレンダーIDには、フットサルカレンダーを指定
    calendar_id = "gjjbveklj6fmjsqofkklbmbubg@group.calendar.google.com"
    # 今日～来月末までの予定を追加
    today = datetime.date.today()
    this_month_first_day = datetime.date(today.year, today.month, 1)
    dtfrom = (today).isoformat() + "T00:00:00.000000Z"
    dtto   = (this_month_first_day + relativedelta(months=2)).isoformat() + "T00:00:00.000000Z"
    # API実行
    events_results = service.events().list(
            calendarId = calendar_id,
            timeMin = dtfrom,
            timeMax = dtto,
            maxResults = 50,
            singleEvents = True,
            orderBy = "startTime"
        ).execute()
    # API結果から値を取り出す
    events = events_results.get('items', [])
    _events = events
    
    return events

#予約完了：True、予約取り消し：False
def reserveFutsal(name, schedule) :
    
    #返却値
    retFlg = False
    
    #GoogleスプレッドシートにLINE名をセットする
    ### APIの認証を行う
    # API用の認証JSON
    json_file = './TorysFutsal/client_secret.json'
    # スコープ設定
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    # 認証情報作成
    credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
    #OAuth2の資格情報を使用してGoogle APIにログインします。
    gc = gspread.authorize(credentials)
    
    #Googleスプレッドシート読み込み
    workbook = gc.open_by_key('1ltNAIdq_w6FLfZvqvlDyjHyuUyNBkmiCEvypQdQ8bRc')
    worksheet = workbook.worksheet('11月出欠')
    
    #スプレッドシートの構成
    #ID(自動) タイムスタンプ  名前    お住まい    参加予定
    #名前が一致する行の参加日程セルの内容を読み込み、名前がなければ新規行を追加
    col_list = worksheet.col_values(3)
    hit_row = 0
    for col in col_list:
        if col == name:
            hit_row = col_list.index(col) + 1
            break
       
    if hit_row > 0:
        #予約日程が存在すれば日程を削除、存在しなければ追加する
        attend_schedule_cell = worksheet.cell(hit_row, 5)
        attend_schedule_cell_val = attend_schedule_cell.value
        schedule_str= ''
        if schedule in attend_schedule_cell.value:
            #削除
            attend_schedule_cell.value = attend_schedule_cell.value.replace(schedule, '')
            retFlg = False
        else:
            #追加
            attend_schedule_cell.value = attend_schedule_cell.value + ',' + schedule
            retFlg = True
        
        #セル更新
        cells=[]
        cells.append(attend_schedule_cell)
        worksheet.update_cells(cells)
    else:    
        #ID(自動) タイムスタンプ  名前    お住まい    参加予定
        JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')
        now = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S.%f") #"2020/4/26 08:22:00"
        rowToAdd = [None, now, name, None, schedule]
        worksheet.append_row(rowToAdd)
        retFlg = True

    return retFlg
reserveFutsal('namaaaaae', 'scheduleaaaa') 

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except LineBotApiError as e:
        print("Got exception from LINE Messaging API: %s\n" % e.message)
        for m in e.error.details:
            print("  %s: %s" % (m.property, m.message))
        print("\n")
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    
    text = event.message.text

    if text == 'profile':
        if isinstance(event.source, SourceUser):
            profile = line_bot_api.get_profile(event.source.user_id)
            line_bot_api.reply_message(
                event.reply_token, [
                    TextSendMessage(text='Display name: ' + profile.display_name),
                    TextSendMessage(text='Status message: ' + str(profile.status_message))
                ]
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="Bot can't use profile API without user ID"))
    elif text == 'スケジュールを確認':
               
        #Googleカレンダーからフットサル情報を取得
        events = getSchedule() 
        strEvents = ""
        for ev in events:
            JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')
            jst_time_start = dateutil.parser.parse(ev["start"]["dateTime"]).astimezone(JST)
            jst_time_end = dateutil.parser.parse(ev["end"]["dateTime"]).astimezone(JST)
            summary = ev["summary"]
            
            date = jst_time_start.strftime("%Y/%m/%d") #"2020/4/26"
            date_str = jst_time_start.strftime("%-m/%-d(%a) %-H～") + jst_time_end.strftime("%-H時") # '4/26(日) 19時～21時'
            
            strEvents += date_str + summary + "\n"
        
        line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=strEvents))
        
    elif text == '参加申込する':
        #Googleカレンダーからフットサル情報を取得
        events = getSchedule() 
        cols = []
        
        for ev in events:
            JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')
            jst_time_start = dateutil.parser.parse(ev["start"]["dateTime"]).astimezone(JST)
            jst_time_end = dateutil.parser.parse(ev["end"]["dateTime"]).astimezone(JST)
            summary = ev["summary"]
            
            date = jst_time_start.strftime("%Y/%m/%d") #"2020/4/26"
            time_from = jst_time_start.strftime("%H:%M") #"19:00"
            time_to = jst_time_end.strftime("%H:%M") #"21:00"
            date_str = jst_time_start.strftime("%-m/%-d(%a) %-H～") + jst_time_end.strftime("%-H時") # '4/26(日) 19時～21時'
            
            column = CarouselColumn(text=summary, title=date_str, actions=[
                    MessageAction(label='予約/取消', text='予約する:'+ date_str + ' ' +summary)
                ])
            cols.append(column)
        
        carousel_template = CarouselTemplate(columns=cols, imageAspectRatio='square')
        
        template_message = TemplateSendMessage(
            alt_text='参加予約はこちら', template=carousel_template)
        line_bot_api.reply_message(event.reply_token, template_message)
        
    elif text.startswith('予約する:'):
        #例：予約する:03/22(日) 11時～14時 フットサル＠千鳥町
        reserve_date = text.split(':')[1]
        
        #プロフィール取得
        profile = line_bot_api.get_profile(event.source.user_id)
        name = profile.display_name
        
        #予約完了：True、予約取り消し：False
        ret = reserveFutsal(name, reserve_date)
        ret_txt = ''
        
        if ret :
            ret_txt = name + 'さん\n\n' + '【' + reserve_date + '】の予約を完了しました❗\n予約を取り消す場合は、もう一度同じ日程をタップしてください\n\n'
        else :
            ret_txt = name + 'さん\n' + '【' + reserve_date + '】の予約を取り消しました❗\n\n'
        
        ret_txt = ret_txt + '予約状況の確認はメニューの「参加状況確認」をタップ⚽'
        
        line_bot_api.reply_message(
                event.reply_token, [
                    TextSendMessage(text= ret_txt),
            ]
        )
            
    else:
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text='こちらのLINEでやり取りができなくなりました、m(_ _)m\n直接トリスに連絡する場合はこちらへ\n→https://line.me/ti/p/yD_gn9JE5X'))


@handler.add(MessageEvent, message=LocationMessage)
def handle_location_message(event):
    line_bot_api.reply_message(
        event.reply_token,
        LocationSendMessage(
            title='Location', address=event.message.address,
            latitude=event.message.latitude, longitude=event.message.longitude
        )
    )


@handler.add(MessageEvent, message=StickerMessage)
def handle_sticker_message(event):
    line_bot_api.reply_message(
        event.reply_token,
        StickerSendMessage(
            package_id=event.message.package_id,
            sticker_id=event.message.sticker_id)
    )


# Other Message Type
@handler.add(MessageEvent, message=(ImageMessage, VideoMessage, AudioMessage))
def handle_content_message(event):
    if isinstance(event.message, ImageMessage):
        ext = 'jpg'
    elif isinstance(event.message, VideoMessage):
        ext = 'mp4'
    elif isinstance(event.message, AudioMessage):
        ext = 'm4a'
    else:
        return

    message_content = line_bot_api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(dir=static_tmp_path, prefix=ext + '-', delete=False) as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        tempfile_path = tf.name

    dist_path = tempfile_path + '.' + ext
    dist_name = os.path.basename(dist_path)
    os.rename(tempfile_path, dist_path)

    line_bot_api.reply_message(
        event.reply_token, [
            TextSendMessage(text='Save content.'),
            TextSendMessage(text=request.host_url + os.path.join('static', 'tmp', dist_name))
        ])


@handler.add(MessageEvent, message=FileMessage)
def handle_file_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(dir=static_tmp_path, prefix='file-', delete=False) as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        tempfile_path = tf.name

    dist_path = tempfile_path + '-' + event.message.file_name
    dist_name = os.path.basename(dist_path)
    os.rename(tempfile_path, dist_path)

    line_bot_api.reply_message(
        event.reply_token, [
            TextSendMessage(text='Save file.'),
            TextSendMessage(text=request.host_url + os.path.join('static', 'tmp', dist_name))
        ])


@handler.add(FollowEvent)
def handle_follow(event):
    app.logger.info("Got Follow event:" + event.source.user_id)
    line_bot_api.reply_message(
        event.reply_token, TextSendMessage(text='Got follow event'))


@handler.add(UnfollowEvent)
def handle_unfollow(event):
    app.logger.info("Got Unfollow event:" + event.source.user_id)


@handler.add(JoinEvent)
def handle_join(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text='Joined this ' + event.source.type))


@handler.add(LeaveEvent)
def handle_leave():
    app.logger.info("Got leave event")


@handler.add(PostbackEvent)
def handle_postback(event):
    if event.postback.data == 'ping':
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text='pong'))
    elif event.postback.data == 'datetime_postback':
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=event.postback.params['datetime']))
    elif event.postback.data == 'date_postback':
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=event.postback.params['date']))


@handler.add(BeaconEvent)
def handle_beacon(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text='Got beacon event. hwid={}, device_message(hex string)={}'.format(
                event.beacon.hwid, event.beacon.dm)))


@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text='Got memberJoined event. event={}'.format(
                event)))


@handler.add(MemberLeftEvent)
def handle_member_left(event):
    app.logger.info("Got memberLeft event")


@app.route('/static/<path:path>')
def send_static_content(path):
    return send_from_directory('static', path)    

def lambda_handler(event, context):
    signature = event["headers"]["X-Line-Signature"]
    body = event["body"]
    logger.info(signature)
    logger.info(body)
    
    ok_json = {"isBase64Encoded": False,
               "statusCode": 200,
               "headers": {},
               "body": ""}
    error_json = {"isBase64Encoded": False,
                  "statusCode": 403,
                  "headers": {},
                  "body": "Error"}
    
    try:
        handler.handle(body, signature)
    except LineBotApiError as e:
        logger.error("Got exception from LINE Messaging API: %s\n" % e.message)
        for m in e.error.details:
            logger.error("  %s: %s" % (m.property, m.message))
        return error_json
    except InvalidSignatureError:
        return error_json
    return ok_json