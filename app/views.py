'django.middleware.csrf.CsrfViewMiddleware'
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
import threading

import select
from django.contrib.auth import login
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from queue import Queue

from socketio import Server

from app import Utils
import time
from collections import defaultdict

request_timestamps = defaultdict(list)  # 用于记录每个客户端的请求时间戳

# 全局字典记录每个客户端的最后活动时间
last_active = {}
# 设置超时时间（单位：秒）
INACTIVE_TIMEOUT = 300  # 5 分钟
# Create your views here.
userdata = None
rootpath = None
prefix = None

sio = Server(cors_allowed_origins='*', async_mode="eventlet")
# 增加线程锁来保护全局 clients 字典
clients_lock = threading.Lock()
# will be used as global variables
fd = None
child_pid = None

# 全局状态存储
clients = defaultdict(lambda: {"fd": None, "child_pid": None, "logs": Queue(maxsize=50)})

def getRootPath():
    global rootpath
    if rootpath is None:
        with open('configuration.json', 'r') as json_f:
            jsonObj=json.load(json_f)
            rootpath=jsonObj["rootpath"]
    return rootpath

def getPrefix():
    global prefix
    if prefix is None:
        with open('configuration.json', 'r') as json_f:
            jsonObj=json.load(json_f)
            prefix=jsonObj["prefix"]
    return prefix

def needUserCookies(func):
    def wrapper(req):
        if isAuthenticated(req.COOKIES.get('username'), req.COOKIES.get('password')):
            return func(req)
        return login(req)
    return wrapper


def login(req):
    return render(req, "login.html", {'prefix': getPrefix()})


def error(req):
    return HttpResponse("ERROR check your password!")


def isAuthenticated(username, password):
    global userdata
    if userdata == None:
        with open('configuration.json','r') as json_f:
            jsonObj=json.load(json_f)
        userdata={jsonObj["username"]:jsonObj["password"]}
    try:
        if userdata[username] == password:
            return True
    except Exception:
        return False


@csrf_exempt
def checkPassword(req):
    data = json.loads(req.body)
    username = data['username']
    password = data['password']
    if isAuthenticated(username, password):
        responseJson = {
            "ok": '/index',
        }
        response = HttpResponse(json.dumps(responseJson), content_type="application/json")
        response.set_cookie('username', username, 3600)
        response.set_cookie('password', password, 3600)
        return response
    else:
        responseJson = {
            "ok": '/error',
        }
        return HttpResponse(json.dumps(responseJson), content_type="application/json")

@needUserCookies
def main(req):
    return render(req, "index.html", {"rootPath": getRootPath(), 'prefix': getPrefix()})

@csrf_exempt
@needUserCookies
def getDirContent(req):
    data = json.loads(req.body)
    path = data['path']
    if path is not None:
        Folder = Utils.Folder(path)
        dataJson = Folder.getFolderJson()
    else:
        Folder = Utils.Folder(getRootPath())
        dataJson = Folder.getFolderJson()

    return HttpResponse(dataJson, content_type="application/json")

@csrf_exempt
@needUserCookies
def deleteFile(req):
    data = json.loads(req.body)
    deletePath = data['deletePath']
    fileOperator = Utils.fileOperator()
    fileOperator.forceRemove(deletePath)
    response = {
        "ok": True,

    }
    return HttpResponse(json.dumps(response), content_type="application/json")

@csrf_exempt
@needUserCookies
def downloadFile(req):
    data = json.loads(req.body)
    downloadPath = data['downloadPath']
    fileOperator = Utils.fileOperator()
    return fileOperator.zipFilesInResponse(downloadPath)

@csrf_exempt
@needUserCookies
def uploadFiles(req):
    response = {
        "ok": True,
    }
    try:
        file = req.FILES.get('file', None)
        path = req.META.get("HTTP_PATH").encode('utf-8').decode("unicode_escape")
        if path == 'rootPath':
            path = getRootPath()

        if os.path.isfile(path) or (not os.path.exists(path)):
            path = os.path.dirname(path)

        with open(path + "/" + file.name, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
    except Exception:
        response = {
            "ok": "上传失败",
        }

    return HttpResponse(json.dumps(response), content_type="application/json")

def rate_limit(client_id, max_requests=15, time_window=1.0):
    """
    限制每个客户端的请求频率。
    - max_requests: 时间窗口内的最大请求数
    - time_window: 时间窗口长度（秒）
    """
    now = time.time()
    timestamps = request_timestamps[client_id]
    timestamps.append(now)
    # 清除窗口外的请求记录
    request_timestamps[client_id] = [t for t in timestamps if now - t <= time_window]
    return len(request_timestamps[client_id]) <= max_requests

def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

def read_and_forward_pty_output(client_id):
    """
     从子进程读取输出并通过 WebSocket 批量发送给客户端。
     """
    max_read_bytes = 1024 * 20
    batch_size = 5  # 每次最多发送5条消息
    while True:
        sio.sleep(0.05)  # 稍微增加等待时间，减少循环频率
        with clients_lock:
            client = clients.get(client_id)
            if not client or client["fd"] is None:
                print(f"Client {client_id} process killed or disconnected")
                return
            fd = client["fd"]

        try:
            (data_ready, _, _) = select.select([fd], [], [], 0)
            if data_ready:
                output = os.read(fd, max_read_bytes).decode(errors='replace')
                with clients_lock:
                    client["logs"].put(output)

                # 聚合消息后发送
                messages = []
                while not client["logs"].empty() and len(messages) < batch_size:
                    messages.append(client["logs"].get())
                if messages:
                    sio.emit("message", {"output": "".join(messages)}, room=client["sid"])
        except OSError as e:
            print(f"Error reading from fd for client {client_id}: {e}")
            return

@sio.event
def connect(sid, environ):
    """
    WebSocket连接事件处理。
    """
    query = environ.get("QUERY_STRING", "")
    client_id = None
    if query:
        from urllib.parse import parse_qs
        client_id = parse_qs(query).get("clientId", [None])[0]
    print(f"Client connected: {client_id}")

    with clients_lock:
        client = clients[client_id]
        client["sid"] = sid
        sio.save_session(sid, {"client_id": client_id})

        if client["child_pid"] is None:
            # 启动子进程
            child_pid, fd = pty.fork()
            if child_pid == 0:
                subprocess.run('bash')
            else:
                client.update({"fd": fd, "child_pid": child_pid})
                print(f"Started bash for client {client_id}")
        else:
            print(f"Reusing existing bash session for client {client_id}")

        # 启动后台任务以监听 Bash 输出
        sio.start_background_task(read_and_forward_pty_output, client_id)

        # 发送缓存日志
        while not client["logs"].empty():
            output = client["logs"].get()
            sio.emit("message", {"output": output}, room=sid)

@sio.event
def disconnect(sid):
    """
       处理客户端断开连接。
       """
    session = sio.get_session(sid)
    client_id = session["client_id"]
    print(f"Client {client_id} disconnected")

    with clients_lock:
        # 清除客户端的 sid，但保留会话数据以供可能的重连
        clients[client_id]["sid"] = None
        last_active[client_id] = time.time()  # 标记断开时间

@sio.event
def send_message(sid, data):
    """
    处理客户端发送到 Bash 的消息。
    """
    session = sio.get_session(sid)
    client_id = session["client_id"]

    if not rate_limit(client_id):
        sio.emit("message", {"error": "Request rate limit exceeded"}, room=sid)
        return

    with clients_lock:
        fd = clients.get(client_id, {}).get("fd")
    if fd:
        try:
            os.write(fd, data["input"].encode())
        except OSError as e:
            print(f"Error writing to fd for client {client_id}: {e}")

@sio.event
def resize(sid, message):
    """
    处理客户端的终端大小调整请求。
    """
    session = sio.get_session(sid)
    client_id = session["client_id"]
    with clients_lock:
        fd = clients[client_id]["fd"]
    if fd:
        set_winsize(fd, message["rows"], message["cols"])

def cleanup_inactive_clients():
    """
    定期检查并清理超过 5 分钟未活动的客户端。
    """
    while True:
        time.sleep(60)  # 每分钟检查一次
        with clients_lock:
            now = time.time()
            inactive_clients = [
                client_id for client_id, timestamp in last_active.items()
                if now - timestamp > INACTIVE_TIMEOUT
            ]
            for client_id in inactive_clients:
                client = clients.pop(client_id, None)
                if client:
                    # 关闭相关文件描述符和子进程
                    if client["fd"]:
                        os.close(client["fd"])
                    if client["child_pid"]:
                        try:
                            os.kill(client["child_pid"], signal.SIGKILL)
                        except OSError:
                            pass
                    print(f"Client {client_id} removed due to inactivity")
                last_active.pop(client_id, None)

# 在服务器启动时，启动一个后台线程处理清理任务
import threading
threading.Thread(target=cleanup_inactive_clients, daemon=True).start()