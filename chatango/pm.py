import sys
import time
import asyncio
import logging
import traceback

from .utils import get_token, gen_uid
from .exceptions import AlreadyConnectedError
from .user import User, Friend
from .message import _process_pm, message_cut


logger = logging.getLogger(__name__)

class Socket:
    def __init__(self, client):
        self.client = client
        self._first = True
        self._connected = False
        self._recv = None
        self._connection = None
        self._recv_task = None
        self._ping_task = None

    async def _connect(self, server: str, port: int):
        """
        user_name, password. For the socket client
        """
        self._recv, self._connection = await asyncio.open_connection(server, port)
        self._recv_task = asyncio.create_task(self._do_recv())
        self._ping_task = asyncio.create_task(self._do_ping())

    @property
    def connected(self):
        return self._connected

    async def cancel(self):
        self._connected = False
        self._recv_task.cancel()
        self._ping_task.cancel()
        await self._connection.close()

    async def _send_command(self, *args, terminator="\r\n\0"):
        if self._first_command:
            terminator = "\x00"
            self._first_command = False
        else:
            terminator = "\r\n\0"
        message = ":".join(args) + terminator
        self._connection.write(message.encode())
        await self._connection.drain()

    async def _do_ping(self):
        while True:
            await asyncio.sleep(20)
            # ping is an empty message
            await self._send_command("\r\n", terminator="\x00")
            await self.client._call_event("pm_ping", self)
            if not self.connected:
                break

    async def _do_recv(self):
        while True:
            # TODO if the rcv is higher than bytes, may is cutted
            rcv = await self._recv.read(2048)
            await asyncio.sleep(0.0001)
            if rcv:  # si recibe datos.
                data = rcv.decode()
                if data == "\r\n\x00":  # pong
                    await self._do_process("")
                else:
                    recv = data.split("\r\n\x00")  # event
                    for r in recv:
                        if r != "":
                            await self._do_process(r)
            else:
                self._recv.close()
                print(f"Disconnected from {self}")
            if not self.connected:
                break
        raise ConnectionAbortedError

    async def _do_process(self, recv):
        """
        Process socket event
        """
        if not recv:
            cmd = "pong"
            args = ""
        else:
            cmd, _, args = recv.partition(":")
            args = args.split(":")
        if hasattr(self, f"_rcmd_{cmd}"):
            try:
                await getattr(self, f"_rcmd_{cmd}")(args)
            except:
                logger.error(f"Error while handling command {cmd}")
                traceback.print_exc(file=sys.stderr)
        else:
            logger.error(f"Unhandled received command {cmd}")


class PM(Socket):
    def __init__(self, client):
        super().__init__(client)
        self.server = "c1.chatango.com"
        self.port = 443
        self.__token = None
        self._first_command = True
        self._correctiontime = 0

        # misc
        self._uid = gen_uid()
        self._user = None
        self._silent = 0
        self._maxlen = 11600
        self._friends = dict()
        self._blocked = list()
        self._premium = False
        self._history = list()

    def __dir__(self):
        return [
            x
            for x in set(list(self.__dict__.keys()) + list(dir(type(self))))
            if x[0] != "_"
        ]

    def __repr__(self):
        return "<PM>"

    @property
    def name(self):
        return repr(self)

    @property
    def is_pm(self):
        return True

    @property
    def user(self):
        return self._user

    @property
    def premium(self):
        return self._premium

    @property
    def history(self):
        return self._history

    @property
    def blocked(self):
        return self._blocked

    @property
    def friends(self):
        return list(self._friends.keys())

    async def connect(self, user_name: str, password: str):
        if self.connected:
            raise AlreadyConnectedError(self.name)
        await self._connect(self.server, self.port)
        await self._login(user_name, password)

    async def block(self, user):  # TODO
        if isinstance(user, User):
            user = user.name
        if user not in self._blocked:
            await self._send_command("block", user, user, "S")
            self._blocked.append(User(user))
            await self.client._call_event("pm_block", User(user))

    async def unblock(self, user):
        if isinstance(user, User):
            user = user.name
        if user in self._blocked:
            await self._send_command("unblock", user)
            await self.client._call_event("pm_unblock", User(user))
            return True

    def get_friend(self, user):
        if isinstance(user, User):
            user = user.name
        if user.lower() in self.friends:
            return self._friends[user]
        return None

    def _add_to_history(self, args):
        if len(self.history) >= 10000:
            self._history = self._history[1:]
        self._history.append(args)

    async def enable_bg(self):
        await self._send_command("msgbg", "1")

    async def disable_bg(self):
        await self._send_command("msgbg", "0")

    async def addfriend(self, user_name):
        user = user_name
        friend = self.get_friend(user)
        if not friend:
            await self._send_command("wladd", user_name.lower())

    async def unfriend(self, user_name):
        user = user_name
        friend = self.get_friend(user)
        if friend:
            await self._send_command("wldelete", friend.name)

    async def _login(self, user_name: str, password: str):
        self.__token = await get_token(user_name, password)
        if self.__token:
            await self._send_command("tlogin", self.__token, "2", self._uid)
            self._connected = True
            self._user = User(str(user_name))

    async def send_message(self, target, message: str, use_html: bool = False):
        if isinstance(target, User):
            target = target.name
        if self._silent > time.time():
            await self.client._call_event("pm_silent", message)
        else:
            if len(message) > 0:
                message = message  # format_videos(self.user, message)
                nc, fs, fc, ff = (
                    f"<n{self.user.styles.name_color}/>",
                    f"{self.user.styles.font_size}",
                    f"{self.user.styles.font_color}",
                    f"{self.user.styles.font_face}",
                )
                for msg in message_cut(message, self._maxlen):
                    msg = f'{nc}<m v="1"><g xs0="0"><g x{fs}s{fc}="{ff}">{msg}</g></g></m>'
                    await self._send_command("msg", target.lower(), msg)

    async def _rcmd_seller_name(self, args):
        await self.client._call_event("pm_connect", self)

    async def _rcmd_pong(self, args):
        await self.client._call_event("pm_pong", self)

    async def _rcmd_premium(self, args):
        if args and args[0] == "210":
            self._premium = True
        else:
            self._premium = False
        if self.premium:
            await self.enable_bg()

    async def _rcmd_time(self, args):
        self._connectiontime = float(args[0])
        self._correctiontime = float(self._connectiontime) - time.time()

    async def _rcmd_DENIED(self, args):
        await self.client._call_event("pm_denied", self, args)

    async def _rcmd_OK(self, args):
        self._connected = True
        if self.friends or self.blocked:
            self.friends.clear()
            self.blocked.clear()
        await self._send_command("getpremium")
        await self._send_command("wl")
        await self._send_command("getblock")

    async def _rcmd_toofast(self, args):
        self._silent = time.time() + 12  # seconds to wait
        await self.client._call_event("pm_toofast")

    async def _rcmd_msglexceeded(self, args):
        await self.client._call_event("pm_msglexceeded")

    async def _rcmd_msg(self, args):
        msg = await _process_pm(self, args)
        self._add_to_history(msg)
        await self.client._call_event("pm_message", msg)

    async def _rcmd_msgoff(self, args):
        msg = await _process_pm(self, args)
        msg._offline = True
        self._add_to_history(msg)

    async def _rcmd_wlapp(self, args):
        pass

    async def _rcmd_wloffline(self, args):
        pass

    async def _rcmd_wlonline(self, args):
        pass

    async def _rcmd_wl(self, args):
        # Restart contact list
        self._friends.clear()
        # Iterate over each contact
        for i in range(len(args) // 4):
            name, last_on, is_on, idle = args[i * 4 : i * 4 + 4]
            user = User(name)
            friend = Friend(user, self)
            if last_on == "None":
                last_on = 0
            if is_on in ["off", "offline"]:
                friend._status = "offline"
            elif is_on in ["on", "online"]:
                friend._status = "online"
            elif is_on in ["app"]:
                friend._status = "app"
            friend._check_status(float(last_on), None, int(idle))
            self._friends[str(user.name)] = friend
            await self._send_command("track", user.name)

    async def _rcmd_track(self, args):
        friend = self._friends[args[0]] if args[0] in self.friends else None
        if friend:
            friend._idle = False
            if args[2] == "online":
                friend._last_active = time.time() - (int(args[1]) * 60)
            elif args[2] == "offline":
                friend._last_active = float(args[1])
            if args[1] in ["0"] and args[2] in ["app"]:
                friend._status = "app"
            else:
                friend._status = args[2]

    async def _rcmd_idleupdate(self, args):
        friend = self._friends[args[0]] if args[0] in self.friends else None
        if friend:
            friend._last_active = time.time()
            friend._idle = True if args[1] == "0" else False

    async def _rcmd_status(self, args):
        friend = self._friends[args[0]] if args[0] in self.friends else None
        if friend == None:
            return
        status = True if args[2] == "online" else False
        friend._check_status(float(args[1]), status, 0)
        await self.client._call_event(f"pm_contact_{args[2]}", friend)

    async def _rcmd_block_list(self, args):
        await self.client._call_event("pm_block_list")

    async def _rcmd_wladd(self, args):
        if args[1] == "invalid":
            return
        friend = self._friends[args[0]] if args[0] in self.friends else None
        if not friend:
            friend = Friend(User(args[0]), self)
            self._friends[args[0]] = friend
            await self.client._call_event("pm_contact_addfriend", friend)
            await self._send_command("wl")
            await self._send_command("track", args[0].lower())

    async def _rcmd_wldelete(self, args):
        if args[1] == "deleted":
            friend = args[0]
            if friend in self._friends:
                del self._friends[friend]
                await self.client._call_event("pm_contact_unfriend", args[0])
